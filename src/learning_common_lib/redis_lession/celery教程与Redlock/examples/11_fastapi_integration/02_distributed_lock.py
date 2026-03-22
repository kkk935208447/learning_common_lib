"""
目标: 对比固定 TTL 锁在短任务与长任务中的表现 (Fixed TTL Lock Comparison)
关键概念:
  - 单 Redis 锁已经可以保护分布式部署的多个服务实例
  - 短任务 + 固定 TTL 通常够用
  - 长任务超过 TTL 后，即使业务没做完，也可能已经失锁
关键 API: redis.lock.Lock, 上下文管理器, timeout, blocking_timeout, pttl()
运行方式:
  Client: python examples/11_fastapi_integration/02_distributed_lock.py
预期现象:
  - 基础获取/释放和竞争互斥都能正常工作
  - 固定 TTL 在短任务下表现正常，TTL 会一路倒计时到任务结束
  - 同样的固定 TTL 放到长任务里，会出现“任务仍在跑，但 TTL 已归零”
  - 客户端会直接打印 Redis 中的 TTL 时间轴，不依赖额外日志
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from typing import Any

import redis

# 与教程其他示例共用本地 Redis；decode_responses=True 便于直接打印字符串形式的 key/value
# 该文档演示的 redis 是同步的库，你也可以用 import redis.asyncio 来引入异步 Redis 客户端。
redis_client = redis.Redis(host="localhost", port=6379, password="123456", db=2, decode_responses=True)


def print_section(title: str) -> None:
    print(f"── {title} ──")


def format_pttl(pttl_ms: int) -> str:
    """将 PTTL 毫秒值转成人类可读说明（Redis 约定：-2 无 key，-1 无过期）。"""
    if pttl_ms == -2:
        return "key 不存在"
    if pttl_ms == -1:
        return "无过期时间"
    return f"{pttl_ms / 1000:.2f}s"


def describe_ttl(previous_ms: int | None, current_ms: int) -> str:
    """根据相邻两次 PTTL 快照，生成时间轴上这一行的简短状态说明。"""
    if current_ms == -2 and previous_ms is None:
        return "等待持有者进入临界区"
    if current_ms > 0 and (previous_ms is None or previous_ms == -2):
        return "锁刚刚获取成功"
    if previous_ms is not None and previous_ms > 0 and current_ms == -2:
        return "TTL 已归零，锁已过期或已释放"
    if current_ms > 0:
        return "锁仍在倒计时"
    return "锁不存在"


async def clear_demo_keys() -> None:
    """清理本示例写入的 demo:*，避免多次运行互相干扰。"""
    # scan_iter：游标式 SCAN（redis-py 封装），按模式增量遍历；比 KEYS 更适合生产，避免单次阻塞整个实例
    keys = await asyncio.to_thread(lambda: list(redis_client.scan_iter("demo:*")))
    if keys:
        # DEL 可一次删多个 key；*keys 展开为可变参数
        await asyncio.to_thread(redis_client.delete, *keys)


async def read_pttl(lock_key: str) -> int:
    """异步包装 PTTL，避免在协程里直接调阻塞 Redis 客户端。"""
    # PTTL：Redis 命令，返回毫秒剩余时间；-2 无此 key，-1 存在但无过期（本示例锁 key 一般带 TTL）
    return await asyncio.to_thread(redis_client.pttl, lock_key)


async def key_exists(lock_key: str) -> bool:
    """场景结束后检查锁 key 是否仍存在（过期/释放后可能为 False）。"""
    # EXISTS：返回整数个数；单 key 时 >0 即存在
    return bool(await asyncio.to_thread(redis_client.exists, lock_key))


@contextmanager
def fixed_ttl_lock(name: str, timeout: int):
    """最小固定 TTL 锁上下文管理器，用来直观展示锁边界。

    thread_local=False：同一进程内多个线程可共享同一 Lock 对象语义上的“身份”，
    与默认 thread_local=True（每线程一份 token）不同；本示例在子线程里持锁、主协程探测，需关闭 thread local。
    """
    # redis-py Lock：timeout=锁在 Redis 里的生存时间（秒），到期 key 被删即“失锁”；不是业务执行超时
    lock = redis_client.lock(name, timeout=timeout, thread_local=False)
    # blocking=True 会等锁；blocking_timeout 是“最多等多久才放弃获取”，与上面的 lock timeout 含义不同
    acquired = lock.acquire(blocking=True, blocking_timeout=1)
    if not acquired:
        raise RuntimeError(f"获取锁失败: {name}")
    try:
        yield lock
    finally:
        # release：Lua 校验 token 后删除；若已过期/被删或 token 不匹配会抛 LockError
        lock.release()


async def probe_same_lock(lock_name: str, timeout: int, label: str) -> bool:
    """非阻塞再申请同一把锁：若成功说明当前无持有者（或已过期）"""
    ttl_before = await read_pttl(lock_name)
    probe = redis_client.lock(lock_name, timeout=timeout, thread_local=False)
    # blocking=False：立即返回，抢不到就 False（TRYLOCK 语义），用于探测“此刻能否再拿锁”
    acquired = await asyncio.to_thread(probe.acquire, blocking=False)
    print(f"  {label}: ttl={format_pttl(ttl_before)}, acquired={acquired}")
    if acquired:
        await asyncio.to_thread(probe.release)
        print(f"  {label}: release=True")
    return acquired


async def wait_until_lock_seen(lock_name: str, timeout_s: float = 2.0) -> None:
    """持有者在线程里稍晚才 acquire，主协程先等到 key 出现再打印时间轴，避免 t=0 全是“尚未建立”。"""
    waited = 0.0
    while waited < timeout_s:
        ttl_ms = await read_pttl(lock_name)
        # -1：key 在但无过期时间；redis-py 锁正常会带 TTL，这里一并视为“锁已可见”
        if ttl_ms > 0 or ttl_ms == -1:
            print(f"  锁已建立: ttl={format_pttl(ttl_ms)}，后续时间轴从这里开始计时")
            return
        await asyncio.sleep(0.1)
        waited += 0.1
    print("  ⚠️ 等待锁建立超时，下面继续按当前状态观察")


async def monitor_lock_timeline(
    lock_name: str,
    *,
    timeout: int,
    work_seconds: int,
    probe_after: int,
    label: str,
) -> bool:
    """每秒读一次 PTTL，打印“剩余 TTL + 状态”；在 probe_after 秒做一次 probe_same_lock。"""
    await wait_until_lock_seen(lock_name)
    print("  时间点      剩余 TTL      观察")
    previous_ms: int | None = None
    probe_acquired = False
    for second in range(work_seconds + 1):
        ttl_ms = await read_pttl(lock_name)
        # 每秒采样一次：观察 TTL 递减；若提前变 -2 多为过期或已释放
        note = describe_ttl(previous_ms, ttl_ms)
        print(f"  t={second:>2}s   {format_pttl(ttl_ms):<12} {note}")
        if second == probe_after:
            probe_acquired = await probe_same_lock(lock_name, timeout, f"{label} / 第 {second}s 探测")
        previous_ms = ttl_ms
        await asyncio.sleep(1)
    return probe_acquired


async def run_fixed_ttl_scenario(
    *,
    label: str,
    timeout: int,        # 锁超时（秒），超时后 redis 自动删锁即“释放成功”
    work_seconds: int,   # 任务耗时秒数
    probe_after: int,    # 锁中间探测秒数
) -> dict[str, Any]:
    """并发结构：子线程里阻塞 sleep 模拟业务；主 asyncio 循环负责监控与中途探测。"""
    lock_name = f"demo:{label}"

    def holder() -> dict[str, Any]:
        # 在独立线程中持锁，避免阻塞事件循环；time.sleep 模拟 CPU/IO 混合的长耗时临界区
        try:
            with fixed_ttl_lock(lock_name, timeout):
                print(
                    f"  持有者: 进入上下文 -> {lock_name}, "
                    f"timeout={timeout}s, work={work_seconds}s"
                )
                time.sleep(work_seconds)
            print("  持有者: 离开上下文，释放成功")
            release_status = "released"
            holder_acquired = True
        except RuntimeError as exc:
            print(f"  持有者: 获取锁失败 -> {exc}")
            release_status = "not_acquired"
            holder_acquired = False
        except redis.exceptions.LockError as exc:
            # 锁已因 TTL 过期被 Redis 删掉，或 token 已失效时，release 会抛 LockError
            print(
                "  持有者: 离开上下文时释放失败，"
                f"说明锁在任务结束前已不属于自己 -> {type(exc).__name__}"
            )
            release_status = type(exc).__name__
            holder_acquired = True
        return {"holder_acquired": holder_acquired, "release_status": release_status}

    # 与 monitor 并行：监控协程不阻塞在 sleep 上，可持续轮询 PTTL
    holder_future = asyncio.create_task(asyncio.to_thread(holder))
    probe_acquired = await monitor_lock_timeline(
        lock_name,
        timeout=timeout,
        work_seconds=work_seconds,
        probe_after=probe_after,
        label=label,
    )
    holder_info = await holder_future
    lock_exists_after_finish = await key_exists(lock_name)
    return {
        "label": label,
        "timeout": timeout,
        "work_seconds": work_seconds,
        "probe_after": probe_after,
        "probe_acquired_midway": probe_acquired,
        "lock_exists_after_finish": lock_exists_after_finish,
        **holder_info,
    }


async def main() -> None:
    print("🚀 固定 TTL 分布式锁对比示例\n")
    print("下面的 TTL 时间轴由客户端直接读取 Redis，因此能直观看到锁什么时候失效。\n")
    await clear_demo_keys()

    # --- 场景 A/B：同步演示，用 to_thread 避免阻塞事件循环 ---
    print_section("场景 A: 基础获取 / 释放")
    def basic_context_demo() -> None:
        with fixed_ttl_lock("demo:basic_lock", timeout=1000):  # 单位：秒
            print("  ✅ 获取锁: True")
            # redis-py 锁底层会写带随机 value 的 key；exists 只判断 key 是否存在
            print(f"  ✅ 锁存在: {bool(redis_client.exists('demo:basic_lock'))}")
        print(f"  ✅ 释放后仍存在: {bool(redis_client.exists('demo:basic_lock'))}\n")

    await asyncio.to_thread(basic_context_demo)

    print_section("场景 B: 竞争互斥")
    def competition_demo() -> None:
        with fixed_ttl_lock("demo:competition", timeout=10):
            print("  Worker A: 通过上下文管理器持有锁")
            # 新建 Lock 对象仅为了在同一会话里再试抢；名称相同即争同一把锁
            contender = redis_client.lock("demo:competition", timeout=100, thread_local=False)
            print(f"  A 未释放锁前 Worker B 尝试获得锁 [False/True]: acquired={contender.acquire(blocking=False)}")
        # A 已释放后，第二个 Lock 实例仍指向同一 Redis key，可再次 acquire
        second_try = redis_client.lock("demo:competition", timeout=100, thread_local=False)
        reacquired = second_try.acquire(blocking=False)
        print(f"  A 释放锁后 Worker B 再次尝试 [False/True]: acquired={reacquired}")
        if reacquired:
            second_try.release()
        print("  结论: 同一时刻只有一个持有者。\n")

    await asyncio.to_thread(competition_demo)

    # --- 场景 C/D：timeout < work_seconds 时，长任务会暴露“固定 TTL 不续期”的问题 ---
    print_section("场景 C: 固定 TTL 放在短任务里，通常是够用的")
    short_case = await run_fixed_ttl_scenario(
        label="short-task-ok",
        timeout=5,
        work_seconds=2,
        probe_after=1,
    )
    print(f"  ✅ {short_case}")
    print("  结论: 任务完成时间短于 TTL 时，固定 TTL 锁没有问题。\n")

    print_section("场景 D: 固定 TTL 放在长任务里，会出现中途失锁")
    long_case = await run_fixed_ttl_scenario(
        label="long-task-risk",
        timeout=3,
        work_seconds=6,
        probe_after=4,
    )
    print(f"  ✅ {long_case}")
    print("  结论: 原任务还在执行，但 TTL 已归零，探测者(其他任务)已经能拿到锁。\n")

    print_section("最终总结")
    rows = [
        ("短任务 + TTL", "通常够用", "业务完成前锁不会过期"),
        ("长任务 + TTL", "存在风险", "任务没做完，锁可能已经失效"),
        ("下一步", "需要看门狗", "让锁在长任务期间持续续期"),
    ]
    for label, value, note in rows:
        print(f"  {label:<14} {value:<10} {note}")

    # 清空案例的锁
    await clear_demo_keys()
    # close：关闭连接池/连接（redis-py 5.x 推荐 close；旧版常用 connection_pool.disconnect）
    await asyncio.to_thread(redis_client.close)


if __name__ == "__main__":
    asyncio.run(main())
