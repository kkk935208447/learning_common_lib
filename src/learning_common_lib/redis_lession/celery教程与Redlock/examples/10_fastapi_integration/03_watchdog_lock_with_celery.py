"""
目标: 演示企业级 python-redis-lock + Celery 长任务锁续期
关键概念:
  - auto_renewal=True 会启动后台看门狗，自动为长任务续期
  - 锁底座仍然是单 Redis，但可以保护分布式部署的多个 worker / service 实例
  - 任务执行时间可以明显超过初始 expire
关键 API: redis_lock.Lock, auto_renewal, templates.distributed_lock.distributed_lock
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/10_fastapi_integration
运行方式:
  Worker: celery -A examples.10_fastapi_integration.03_watchdog_lock_with_celery worker -l info -P solo
  Client: python examples/10_fastapi_integration/03_watchdog_lock_with_celery.py
预期现象:
  - 任务持锁时间超过初始 expire，但不会中途丢锁
  - 客户端在任务执行过程中尝试抢同一把锁，会失败
  - 任务结束后客户端再次尝试，可成功拿到锁
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import redis
from celery import Celery, Task

try:
    from templates.distributed_lock import distributed_lock
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates.distributed_lock import distributed_lock  # type: ignore[no-redef]

logging.getLogger("redis_lock").setLevel(logging.ERROR)

app = Celery(
    "examples.10_fastapi_integration.03_watchdog_lock_with_celery",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)

redis_client = redis.Redis(host="localhost", port=6379, password="123456", db=2, decode_responses=True)


@app.task(bind=True, name="examples.watchdog_lock.process_order")
def process_order_with_watchdog(
    self: Task,
    order_id: str,
    work_seconds: int = 8,
    expire_seconds: int = 3,
) -> dict[str, Any]:
    """使用企业模板分布式锁处理长任务。"""
    lock_name = f"order:{order_id}"
    print(f"  🔒 准备获取看门狗锁: {lock_name}")
    with distributed_lock(
        redis_client,
        lock_name,
        timeout=expire_seconds,
        blocking_timeout=1.0,
        auto_renewal=True,
    ):
        print(f"  ✅ 成功获取锁: {lock_name}")
        print(f"  📌 初始过期时间: {expire_seconds}s, 实际工作时长: {work_seconds}s")
        for index in range(work_seconds):
            print(f"  ⏱️ 第 {index + 1}/{work_seconds} 秒，任务仍在执行")
            time.sleep(1)
        print(f"  🔓 业务完成，准备释放锁: {lock_name}")
        return {
            "order_id": order_id,
            "work_seconds": work_seconds,
            "expire_seconds": expire_seconds,
            "watchdog": True,
            "message": "任务执行时长超过初始 expire，但锁通过 auto_renewal 持续续期",
        }


async def probe_same_lock(order_id: str, label: str) -> bool:
    """客户端侧探测同一把锁是否还能被拿到。"""
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
    return acquired


async def main() -> None:
    print("🚀 企业级 python-redis-lock + Celery 示例\n")
    print("说明: 本示例会让任务运行 8 秒，但锁的初始 expire 只有 3 秒。")
    print("说明: 如果没有 auto_renewal，看门狗之外的客户端在中途就可能抢到同一把锁。\n")

    print("── 提交长任务 ──")
    result = await asyncio.to_thread(
        process_order_with_watchdog.delay,
        "ORD-LOCK-1001",
        8,
        3,
    )
    print("  task_id:", result.id)
    print()

    print("── 等待任务进入执行态后探测同一把锁 ──")
    await asyncio.sleep(2)
    await probe_same_lock("ORD-LOCK-1001", "客户端中途探测")
    print()

    print("── 等待任务结束 ──")
    final = await asyncio.to_thread(result.get, timeout=30)
    print("  最终结果:", final)
    await asyncio.to_thread(result.forget)
    print()

    print("── 任务结束后再次探测同一把锁 ──")
    await probe_same_lock("ORD-LOCK-1001", "任务结束后探测")
    print()

    print("── 一句话总结 ──")
    print("  基础过期时间只有 3 秒，但任务跑了 8 秒仍未失锁。")
    print("  这是因为 python-redis-lock 的 auto_renewal 在后台持续续期。")
    redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
