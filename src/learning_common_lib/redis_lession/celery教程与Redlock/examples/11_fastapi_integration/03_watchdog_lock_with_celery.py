"""
目标: 在 async-first worker 中对比“无看门狗”和“有看门狗” (Watchdog Comparison with async task)
关键概念:
  - worker 侧任务已经切到 `custom aio pool + async def task`
  - `auto_renewal=False` 时，长任务中途可能失锁
  - `auto_renewal=True` 时，看门狗会持续续期
关键 API: async_distributed_lock, auto_renewal, redis_lock.Lock
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/11_fastapi_integration
运行方式:
  Worker:
    CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool' \
    celery -A examples.11_fastapi_integration.03_watchdog_lock_with_celery worker -l info -P custom -Q aio_watchdog -c 20
  Client:
    python examples/11_fastapi_integration/03_watchdog_lock_with_celery.py
预期现象:
  - 相同参数下，无看门狗时中途可被抢锁
  - 开启看门狗后，中途不可被抢锁
  - 两个场景在任务结束后都应释放锁
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import redis
from celery import Celery, Task

try:
    from ...templates.distributed_lock import async_distributed_lock
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates.distributed_lock import async_distributed_lock  # type: ignore[no-redef]

logging.getLogger("redis_lock").setLevel(logging.ERROR)

MODULE = "examples.11_fastapi_integration.03_watchdog_lock_with_celery"

app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.task_default_queue = "aio_watchdog"

redis_client = redis.Redis(host="localhost", port=6379, password="123456", db=2, decode_responses=True)


def print_section(title: str) -> None:
    print(f"── {title} ──")


@app.task(bind=True, name=f"{MODULE}.process_order_with_lock_mode")
async def process_order_with_lock_mode(
    self: Task,
    order_id: str,
    work_seconds: int = 8,
    expire_seconds: int = 3,
    auto_renewal: bool = False,
) -> dict[str, Any]:
    lock_name = f"order:{order_id}"
    mode = "watchdog_on" if auto_renewal else "watchdog_off"
    print(f"  🔒 [{mode}] 准备获取锁: {lock_name}")
    async with async_distributed_lock(
        redis_client,
        lock_name,
        timeout=expire_seconds,
        blocking_timeout=1.0,
        auto_renewal=auto_renewal,
    ):
        print(
            f"  ✅ [{mode}] 获取锁成功: expire={expire_seconds}s, "
            f"work={work_seconds}s, auto_renewal={auto_renewal}"
        )
        for index in range(work_seconds):
            print(f"  ⏱️ [{mode}] 第 {index + 1}/{work_seconds} 秒")
            await asyncio.sleep(1)
        return {
            "task_id": self.request.id,
            "order_id": order_id,
            "work_seconds": work_seconds,
            "expire_seconds": expire_seconds,
            "auto_renewal": auto_renewal,
            "task_shape": "async def",
            "message": "业务执行完成",
        }


async def probe_same_lock(order_id: str, label: str) -> bool:
    import redis_lock

    probe = redis_lock.Lock(
        redis_client,
        name=f"order:{order_id}",
        expire=3,
        auto_renewal=False,
    )
    acquired = await asyncio.to_thread(probe.acquire, blocking=False)
    print(f"  {label}: acquired={acquired}")
    if acquired:
        await asyncio.to_thread(probe.release)
        print(f"  {label}: release=True")
    return acquired


async def run_comparison_case(order_id: str, *, auto_renewal: bool) -> dict[str, Any]:
    mode_label = "无看门狗" if not auto_renewal else "有看门狗"
    result = await asyncio.to_thread(
        process_order_with_lock_mode.delay,
        order_id,
        8,
        3,
        auto_renewal,
    )

    await asyncio.sleep(4)
    midway_acquired = await probe_same_lock(order_id, f"{mode_label} / 中途探测")

    payload = await asyncio.to_thread(result.get, timeout=30)
    await asyncio.to_thread(result.forget)

    after_acquired = await probe_same_lock(order_id, f"{mode_label} / 任务结束后探测")
    return {
        "mode": mode_label,
        "midway_probe_acquired": midway_acquired,
        "after_finish_probe_acquired": after_acquired,
        "task_result": payload,
    }


async def main() -> None:
    print("🚀 看门狗续期对比示例（async task）\n")
    print("同样参数: work_seconds=8, expire_seconds=3")
    print("差别只在于 auto_renewal 是否开启。\n")

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
    print("  结论 2: 有看门狗时，锁会在后台续期，中途探测拿不到锁。")
    print("  结论 3: 两种模式在任务结束后都应该把锁释放掉。")
    redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
