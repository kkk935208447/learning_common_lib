"""
目标: 用最小 python-redis-lock 示例看懂看门狗续期 (Minimal Watchdog Demo)
# 注意：python-redis-lock 是同步的库。
关键概念:
  - 这是纯 Redis 锁实验，不依赖 Celery worker
  - `auto_renewal=False` 时，TTL 会自然归零
  - `auto_renewal=True` 时，后台线程会按 `expire * 2 / 3` 周期续期
关键 API: redis_lock.Lock, auto_renewal, pttl(), acquire(blocking=False)
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/11_fastapi_integration
运行方式:
  Client:
    python examples/11_fastapi_integration/03_python_redis_lock_watchdog_minimal.py
预期现象:
  - 相同参数下，无看门狗时 TTL 会掉到 0，中途可被抢锁
  - 开启看门狗后，TTL 会周期性回升，中途不可被抢锁
  - 两个场景在持锁逻辑结束后都应释放锁
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import redis
import redis_lock

WORK_SECONDS = 8
EXPIRE_SECONDS = 3
PROBE_AT_SECOND = 4

redis_client = redis.Redis(host="localhost", port=6379, password="123456", db=2, decode_responses=True)


def print_section(title: str) -> None:
    print(f"── {title} ──")


def lock_resource_name(order_id: str) -> str:
    return f"order:{order_id}"


def lock_key(order_id: str) -> str:
    return f"lock:{lock_resource_name(order_id)}"


def lock_signal_key(order_id: str) -> str:
    return f"lock-signal:{lock_resource_name(order_id)}"


def format_pttl(pttl_ms: int) -> str:
    if pttl_ms == -2:
        return "key 不存在"
    if pttl_ms == -1:
        return "无过期时间"
    return f"{pttl_ms / 1000:.2f}s"


def describe_ttl(previous_ms: int | None, current_ms: int) -> str:
    if current_ms == -2 and previous_ms is None:
        return "等待 holder 获取锁"
    if current_ms > 0 and (previous_ms is None or previous_ms == -2):
        return "holder 已拿到锁"
    if previous_ms is not None and previous_ms > 0 and current_ms == -2:
        return "锁已释放或已过期"
    if previous_ms is not None and previous_ms > 0 and current_ms > previous_ms + 500:
        return "TTL 回升，看门狗已续期"
    if current_ms > 0:
        return "锁仍被持有"
    return "锁不存在"


async def clear_watchdog_keys(order_id: str) -> None:
    await asyncio.to_thread(redis_client.delete, lock_key(order_id), lock_signal_key(order_id))


async def read_lock_pttl(order_id: str) -> int:
    return await asyncio.to_thread(redis_client.pttl, lock_key(order_id))


async def probe_same_lock(order_id: str, expire_seconds: int, label: str) -> bool:
    ttl_before = await read_lock_pttl(order_id)
    probe = redis_lock.Lock(
        redis_client,
        name=lock_resource_name(order_id),
        expire=expire_seconds,
        auto_renewal=False,
    )
    acquired = await asyncio.to_thread(probe.acquire, blocking=False)
    print(f"  {label}: ttl={format_pttl(ttl_before)}, acquired={acquired}")
    if acquired:
        await asyncio.to_thread(probe.release)
        print(f"  {label}: release=True")
    return acquired


async def wait_until_lock_seen(order_id: str, timeout_s: float = 2.0) -> None:
    waited = 0.0
    while waited < timeout_s:
        ttl_ms = await read_lock_pttl(order_id)
        if ttl_ms > 0 or ttl_ms == -1:
            print(f"  锁已建立: ttl={format_pttl(ttl_ms)}，后续时间轴从这里开始计时")
            return
        await asyncio.sleep(0.1)
        waited += 0.1
    print("  ⚠️ 等待 holder 获取锁超时，下面继续按当前状态观察")


async def monitor_lock_timeline(
    order_id: str,
    *,
    mode_label: str,
    work_seconds: int,
    expire_seconds: int,
    probe_after: int,
) -> bool:
    await wait_until_lock_seen(order_id)
    print("  时间点      剩余 TTL      观察")
    previous_ms: int | None = None
    probe_acquired = False
    for second in range(work_seconds + 1):
        ttl_ms = await read_lock_pttl(order_id)
        note = describe_ttl(previous_ms, ttl_ms)
        print(f"  t={second:>2}s   {format_pttl(ttl_ms):<12} {note}")
        if second == probe_after:
            probe_acquired = await probe_same_lock(
                order_id,
                expire_seconds,
                f"{mode_label} / 第 {second}s 探测",
            )
        previous_ms = ttl_ms
        await asyncio.sleep(1)
    return probe_acquired


async def run_case(order_id: str, *, auto_renewal: bool) -> dict[str, Any]:
    mode_label = "无看门狗" if not auto_renewal else "有看门狗"
    await clear_watchdog_keys(order_id)

    def holder() -> dict[str, Any]:
        lock = redis_lock.Lock(
            redis_client,
            name=lock_resource_name(order_id),
            expire=EXPIRE_SECONDS,
            auto_renewal=auto_renewal,
        )
        try:
            with lock:
                print(
                    f"  holder: 进入上下文 -> {lock_key(order_id)}, "
                    f"expire={EXPIRE_SECONDS}s, work={WORK_SECONDS}s, "
                    f"auto_renewal={auto_renewal}"
                )
                time.sleep(WORK_SECONDS)
            print("  holder: 离开上下文，释放成功")
            release_status = "released"
        except Exception as exc:
            print(f"  holder: 离开上下文时异常 -> {type(exc).__name__}: {exc}")
            release_status = type(exc).__name__
        return {"release_status": release_status}

    holder_future = asyncio.create_task(asyncio.to_thread(holder))
    midway_probe_acquired = await monitor_lock_timeline(
        order_id,
        mode_label=mode_label,
        work_seconds=WORK_SECONDS,
        expire_seconds=EXPIRE_SECONDS,
        probe_after=PROBE_AT_SECOND,
    )
    holder_result = await holder_future
    after_finish_probe_acquired = await probe_same_lock(
        order_id,
        EXPIRE_SECONDS,
        f"{mode_label} / 任务结束后探测",
    )
    after_finish_ttl = await read_lock_pttl(order_id)
    await clear_watchdog_keys(order_id)
    return {
        "mode": mode_label,
        "midway_probe_acquired": midway_probe_acquired,
        "after_finish_probe_acquired": after_finish_probe_acquired,
        "after_finish_ttl": format_pttl(after_finish_ttl),
        **holder_result,
    }


async def main() -> None:
    print("🚀 python-redis-lock 最小看门狗示例\n")
    print(f"同样参数: work_seconds={WORK_SECONDS}, expire_seconds={EXPIRE_SECONDS}")
    print("差别只在于 auto_renewal 是否开启。")
    print("这一节不引入 Celery，只看 python-redis-lock 自己如何续期。\n")

    print_section("场景 A: auto_renewal=False，无看门狗")
    without_watchdog = await run_case("ORD-PLAIN-OFF-1001", auto_renewal=False)
    print(f"  ✅ {without_watchdog}\n")

    print_section("场景 B: auto_renewal=True，有看门狗")
    with_watchdog = await run_case("ORD-PLAIN-ON-1001", auto_renewal=True)
    print(f"  ✅ {with_watchdog}\n")

    print_section("并排结论")
    rows = [
        ("无看门狗", without_watchdog["midway_probe_acquired"], without_watchdog["after_finish_probe_acquired"]),
        ("有看门狗", with_watchdog["midway_probe_acquired"], with_watchdog["after_finish_probe_acquired"]),
    ]
    print("  模式         中途能否抢锁   任务结束后能否再次获取")
    print("  -------------------------------------------")
    for label, midway, after_finish in rows:
        print(f"  {label:<10} {str(midway):<14} {after_finish}")
    print()
    print("  结论 1: 无看门狗时，TTL 会自然掉空，中途就可能失锁。")
    print("  结论 2: 有看门狗时，TTL 会周期性回升，中途探测拿不到锁。")
    print("  结论 3: 真正落到 Celery async worker 时，只是持锁逻辑换成了 task。")
    await asyncio.to_thread(redis_client.close)


if __name__ == "__main__":
    asyncio.run(main())
