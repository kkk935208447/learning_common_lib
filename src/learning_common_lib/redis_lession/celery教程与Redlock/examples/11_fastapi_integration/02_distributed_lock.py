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

redis_client = redis.Redis(host="localhost", port=6379, password="123456", db=2, decode_responses=True)


def print_section(title: str) -> None:
    print(f"── {title} ──")


def format_pttl(pttl_ms: int) -> str:
    if pttl_ms == -2:
        return "key 不存在"
    if pttl_ms == -1:
        return "无过期时间"
    return f"{pttl_ms / 1000:.2f}s"


def describe_ttl(previous_ms: int | None, current_ms: int) -> str:
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
    keys = await asyncio.to_thread(lambda: list(redis_client.scan_iter("demo:*")))
    if keys:
        await asyncio.to_thread(redis_client.delete, *keys)


async def read_pttl(lock_key: str) -> int:
    return await asyncio.to_thread(redis_client.pttl, lock_key)


async def key_exists(lock_key: str) -> bool:
    return bool(await asyncio.to_thread(redis_client.exists, lock_key))


@contextmanager
def fixed_ttl_lock(name: str, timeout: int):
    """最小固定 TTL 锁上下文管理器，用来直观展示锁边界。"""
    lock = redis_client.lock(name, timeout=timeout, thread_local=False)
    acquired = lock.acquire(blocking=True, blocking_timeout=1)
    if not acquired:
        raise RuntimeError(f"获取锁失败: {name}")
    try:
        yield lock
    finally:
        lock.release()


async def probe_same_lock(lock_name: str, timeout: int, label: str) -> bool:
    ttl_before = await read_pttl(lock_name)
    probe = redis_client.lock(lock_name, timeout=timeout, thread_local=False)
    acquired = await asyncio.to_thread(probe.acquire, blocking=False)
    print(f"  {label}: ttl={format_pttl(ttl_before)}, acquired={acquired}")
    if acquired:
        await asyncio.to_thread(probe.release)
        print(f"  {label}: release=True")
    return acquired


async def wait_until_lock_seen(lock_name: str, timeout_s: float = 2.0) -> None:
    waited = 0.0
    while waited < timeout_s:
        ttl_ms = await read_pttl(lock_name)
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
    await wait_until_lock_seen(lock_name)
    print("  时间点      剩余 TTL      观察")
    previous_ms: int | None = None
    probe_acquired = False
    for second in range(work_seconds + 1):
        ttl_ms = await read_pttl(lock_name)
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
    timeout: int,
    work_seconds: int,
    probe_after: int,
) -> dict[str, Any]:
    lock_name = f"demo:{label}"

    def holder() -> dict[str, Any]:
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
            print(
                "  持有者: 离开上下文时释放失败，"
                f"说明锁在任务结束前已不属于自己 -> {type(exc).__name__}"
            )
            release_status = type(exc).__name__
            holder_acquired = True
        return {"holder_acquired": holder_acquired, "release_status": release_status}

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

    print_section("场景 A: 基础获取 / 释放")
    def basic_context_demo() -> None:
        with fixed_ttl_lock("demo:basic_lock", timeout=10):
            print("  ✅ 获取锁: True")
            print(f"  ✅ 锁存在: {bool(redis_client.exists('demo:basic_lock'))}")
        print(f"  ✅ 释放后仍存在: {bool(redis_client.exists('demo:basic_lock'))}\n")

    await asyncio.to_thread(basic_context_demo)

    print_section("场景 B: 竞争互斥")
    def competition_demo() -> None:
        with fixed_ttl_lock("demo:competition", timeout=10):
            print("  Worker A: 通过上下文管理器持有锁")
            contender = redis_client.lock("demo:competition", timeout=10, thread_local=False)
            print(f"  Worker B: acquired={contender.acquire(blocking=False)}")
        second_try = redis_client.lock("demo:competition", timeout=10, thread_local=False)
        reacquired = second_try.acquire(blocking=False)
        print(f"  Worker B 再次尝试: acquired={reacquired}")
        if reacquired:
            second_try.release()
        print("  结论: 同一时刻只有一个持有者。\n")

    await asyncio.to_thread(competition_demo)

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
    print("  结论: 原任务还在执行，但 TTL 已归零，探测者已经能拿到锁。\n")

    print_section("最终总结")
    rows = [
        ("短任务 + TTL", "通常够用", "业务完成前锁不会过期"),
        ("长任务 + TTL", "存在风险", "任务没做完，锁可能已经失效"),
        ("下一步", "需要看门狗", "让锁在长任务期间持续续期"),
    ]
    for label, value, note in rows:
        print(f"  {label:<14} {value:<10} {note}")

    await clear_demo_keys()
    await asyncio.to_thread(redis_client.close)


if __name__ == "__main__":
    asyncio.run(main())
