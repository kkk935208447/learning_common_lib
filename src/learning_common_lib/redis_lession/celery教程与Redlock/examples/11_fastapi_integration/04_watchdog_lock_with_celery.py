"""
目标: 在 async-first worker 中对比“无看门狗”和“有看门狗” (Watchdog Comparison with async task)
关键概念:
  - 建议先运行 `03_python_redis_lock_watchdog_minimal2.py`，先看懂纯异步看门狗自己如何续期
  - worker 侧任务已经切到 `custom aio pool + async def task`
  - `auto_renewal=False` 时，长任务中途可能失锁
  - `auto_renewal=True` 时，看门狗会持续续期
  - Redis 客户端使用 `redis.asyncio`，真实锁 key 为 `lock:{逻辑名}`
关键 API: async_distributed_lock, AsyncRedisWatchdogLock, auto_renewal, pttl()
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/11_fastapi_integration
运行方式:
  Worker:
    CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool' \
    celery -A examples.11_fastapi_integration.04_watchdog_lock_with_celery worker -l info -P custom -Q aio_watchdog -c 20
  Client:
    python examples/11_fastapi_integration/04_watchdog_lock_with_celery.py
预期现象:
  - 相同参数下，无看门狗时 TTL 会自然归零，中途可被抢锁
  - 无看门狗场景下，worker 退出锁上下文时可能记录 `LockNotOwnedError` warning；
    这是因为锁早已过期或被后续探测者重新获取，不代表纯异步锁实现本身有 bug
  - 开启看门狗后，TTL 会被周期性拉回安全区，中途不可被抢锁
  - 两个场景在任务结束后都应释放锁
"""

from __future__ import annotations

import asyncio
from typing import Any

import redis.asyncio as aioredis
from celery import Celery, Task

try:
    from ...templates.distributed_lock_aio import (
        AsyncRedisWatchdogLock,
        async_distributed_lock,
    )
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates.distributed_lock_aio import (  # type: ignore[no-redef]
        AsyncRedisWatchdogLock,
        async_distributed_lock,
    )

MODULE = "examples.11_fastapi_integration.04_watchdog_lock_with_celery"
WORK_SECONDS = 8
EXPIRE_SECONDS = 3
PROBE_AT_SECOND = 4

app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.task_default_queue = "aio_watchdog"

redis_client = aioredis.Redis(
    host="localhost",
    port=6379,
    password="123456",
    db=2,
    decode_responses=True,
)


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
        return "等待 worker 获取锁"
    if current_ms > 0 and (previous_ms is None or previous_ms == -2):
        return "worker 已拿到锁"
    if previous_ms is not None and previous_ms > 0 and current_ms == -2:
        return "锁已释放或已过期"
    if previous_ms is not None and previous_ms > 0 and current_ms > previous_ms + 500:
        return "TTL 回升，看门狗已续期"
    if current_ms > 0:
        return "锁仍被持有"
    return "锁不存在"


async def clear_watchdog_keys(order_id: str) -> None:
    await redis_client.delete(lock_key(order_id), lock_signal_key(order_id))


async def read_lock_pttl(order_id: str) -> int:
    return await redis_client.pttl(lock_key(order_id))


@app.task(bind=True, name=f"{MODULE}.process_order_with_lock_mode")
async def process_order_with_lock_mode(
    self: Task,
    order_id: str,
    work_seconds: int = WORK_SECONDS,
    expire_seconds: int = EXPIRE_SECONDS,
    auto_renewal: bool = False,
) -> dict[str, Any]:
    # 这个示例的目的就是对比“锁过期”和“锁被续期”两种路径。
    # 当 auto_renewal=False 且工作时长明显大于 TTL 时，
    # 任务退出上下文时已经不再拥有这把锁，release() 记录 warning 是预期现象。
    async with async_distributed_lock(
        redis_client,
        lock_resource_name(order_id),
        timeout=expire_seconds,
        blocking_timeout=1.0,
        auto_renewal=auto_renewal,
    ):
        await asyncio.sleep(work_seconds)
        return {
            "task_id": self.request.id,
            "order_id": order_id,
            "work_seconds": work_seconds,
            "expire_seconds": expire_seconds,
            "auto_renewal": auto_renewal,
            "task_shape": "async def",
            "message": "业务执行完成",
        }


async def probe_same_lock(order_id: str, expire_seconds: int, label: str) -> bool:
    ttl_before = await read_lock_pttl(order_id)
    probe = AsyncRedisWatchdogLock(
        redis_client,
        name=lock_resource_name(order_id),
        timeout=expire_seconds,
        blocking_timeout=0.0,
        auto_renewal=False,
    )
    acquired = await probe.acquire()
    print(f"  {label}: ttl={format_pttl(ttl_before)}, acquired={acquired}")
    if acquired:
        await probe.release()
        print(f"  {label}: release=True")
    return acquired


async def wait_until_lock_seen(order_id: str, timeout_s: float = 5.0) -> None:
    waited = 0.0
    while waited < timeout_s:
        ttl_ms = await read_lock_pttl(order_id)
        if ttl_ms > 0 or ttl_ms == -1:
            print(f"  锁已建立: ttl={format_pttl(ttl_ms)}，后续时间轴从这里开始计时")
            return
        await asyncio.sleep(0.1)
        waited += 0.1
    print("  ⚠️ 等待 worker 获取锁超时，下面继续按当前状态观察")


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


async def run_comparison_case(order_id: str, *, auto_renewal: bool) -> dict[str, Any]:
    mode_label = "无看门狗" if not auto_renewal else "有看门狗"
    await clear_watchdog_keys(order_id)
    result = await asyncio.to_thread(
        process_order_with_lock_mode.delay,
        order_id,
        WORK_SECONDS,
        EXPIRE_SECONDS,
        auto_renewal,
    )
    monitor_task = asyncio.create_task(
        monitor_lock_timeline(
            order_id,
            mode_label=mode_label,
            work_seconds=WORK_SECONDS,
            expire_seconds=EXPIRE_SECONDS,
            probe_after=PROBE_AT_SECOND,
        )
    )
    payload = await asyncio.to_thread(result.get, timeout=30)
    midway_acquired = await monitor_task
    await asyncio.to_thread(result.forget)
    after_acquired = await probe_same_lock(order_id, EXPIRE_SECONDS, f"{mode_label} / 任务结束后探测")
    final_ttl = await read_lock_pttl(order_id)
    await clear_watchdog_keys(order_id)
    return {
        "mode": mode_label,
        "midway_probe_acquired": midway_acquired,
        "after_finish_probe_acquired": after_acquired,
        "after_finish_ttl": format_pttl(final_ttl),
        "task_result": payload,
    }


async def main() -> None:
    print("🚀 看门狗续期对比示例（async task）\n")
    print("建议先看上一节最小 demo，再来看同样机制落到 Celery worker 中会怎样。\n")
    print(f"同样参数: work_seconds={WORK_SECONDS}, expire_seconds={EXPIRE_SECONDS}")
    print("差别只在于 auto_renewal 是否开启。")
    print("下面的 TTL 时间轴由客户端直接读取 Redis，因此不用盯着 worker 终端。\n")

    print_section("场景 A: auto_renewal=False，无看门狗")
    without_watchdog = await run_comparison_case("ORD-WD-OFF-1001", auto_renewal=False)
    print(f"  ✅ {without_watchdog}\n")

    print_section("场景 B: auto_renewal=True，有看门狗")
    with_watchdog = await run_comparison_case("ORD-WD-ON-1001", auto_renewal=True)
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
    print("  结论 1: 无看门狗时，长任务运行到一半就可能失锁。")
    print("  结论 2: 有看门狗时，TTL 会周期性回升，中途探测拿不到锁。")
    print("  结论 3: 两种模式在任务结束后都应该把锁释放掉。")
    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
