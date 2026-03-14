"""
目标: 用 async task 演示结果过期配置与生命周期管理 (Result Expiry with async tasks)
关键 API: result_expires, result_extended, AsyncResult.forget()
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
运行方式:
  Worker:
    CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool' \
    celery -A examples.05_result_backend.02_result_expiry worker -l info -P custom -Q aio_results -c 20
  Client: python examples/05_result_backend/02_result_expiry.py
预期现象: 展示结果过期配置、扩展元数据、手动清理效果
生产提醒: 务必设置 result_expires，否则 Redis/DB 会无限膨胀
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from celery import Celery
from celery.result import AsyncResult

MODULE = "examples.05_result_backend.02_result_expiry"

app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.update(
    task_default_queue="aio_results",
    result_expires=3600,
    result_extended=True,
)


@app.task(bind=True, name=f"{MODULE}.slow_add")
async def slow_add(self: Any, x: int, y: int) -> int:
    await asyncio.sleep(0.2)
    return x + y


@app.task(bind=True, ignore_result=True, name=f"{MODULE}.notify")
async def notify(self: Any, msg: str) -> None:
    await asyncio.sleep(0.05)
    print(f"  📦 notify: {msg} (结果不存储)")


async def read_state(result: AsyncResult) -> str:
    return await asyncio.to_thread(lambda: result.state)


async def read_ready(result: AsyncResult) -> bool:
    return await asyncio.to_thread(result.ready)


async def main() -> None:
    print("🚀 结果过期与扩展元数据示例（async task）\n")

    print("── result_expires 配置方式 ──")
    print(f"  当前配置 (秒): result_expires = {app.conf.result_expires}")
    app.conf.result_expires = timedelta(hours=2)
    print(f"  修改为 timedelta: result_expires = {app.conf.result_expires}")
    print("  💡 设为 None 可禁用过期 (不推荐，会导致存储膨胀)")
    app.conf.result_expires = 3600
    print()

    print("── 结果生命周期 ──")
    r1 = await asyncio.to_thread(slow_add.delay, 10, 20)
    task_id = r1.id
    print("  阶段 1 - 结果可用:")
    val1 = await asyncio.to_thread(r1.get, timeout=30)
    print(f"    state: {await read_state(r1)}")
    print(f"    result: {val1}")
    print(f"    ready: {await read_ready(r1)}")

    print("  阶段 2 - forget() 手动清理:")
    await asyncio.to_thread(r1.forget)
    r1_check = AsyncResult(task_id, app=app)
    print(f"    清理后 state: {await read_state(r1_check)}")
    print("    💡 forget() 立即删除，不等过期时间")
    print()

    print("── result_extended=True 扩展元数据 ──")
    print(f"  配置: result_extended = {app.conf.result_extended}")
    r2 = await asyncio.to_thread(slow_add.delay, 100, 200)
    r2_val = await asyncio.to_thread(r2.get, timeout=30)
    result_meta: dict[str, Any] = {
        "id": r2.id,
        "state": await read_state(r2),
        "result": r2_val,
    }
    for attr in ("name", "args", "kwargs", "worker", "queue"):
        result_meta[attr] = getattr(r2, attr, "N/A")
    print("  扩展元数据:")
    for key, value in result_meta.items():
        print(f"    {key:.<20} {value!r}")
    print()

    print("── ignore_result 与过期 ──")
    r3 = await asyncio.to_thread(notify.delay, "用户注册成功")
    print("  ignore_result=True 的任务:")
    print(f"    state: {await read_state(r3)}")
    print("    💡 ignore_result=True 的任务不写入 backend，无需担心过期")
    print()

    print("── 结果清理最佳实践 ──")
    practices: list[tuple[str, str]] = [
        ("result_expires", "始终设置，推荐 1-24 小时"),
        ("ignore_result", "不需要结果的任务设为 True"),
        ("forget()", "获取结果后立即调用，主动释放"),
        ("result_extended", "调试时开启，生产按需 (略增存储)"),
        ("backend 选择", "Redis 适合短期结果，DB 适合需要持久化的场景"),
        ("监控", "定期检查 backend 存储大小"),
    ]
    for practice, desc in practices:
        print(f"  ✅ {practice:.<25} {desc}")
    print()

    print("── 不同 backend 的过期机制 ──")
    backends: list[tuple[str, str]] = [
        ("Redis", "利用 Redis TTL 自动过期，最高效"),
        ("Database", "需要定期运行 celery beat + DatabaseCleanup"),
        ("RPC (AMQP)", "结果作为消息，消费后自动删除"),
        ("Filesystem", "需要自行清理文件"),
    ]
    for backend, mechanism in backends:
        print(f"  📋 {backend:.<15} {mechanism}")

    print("\n💡 worker 侧已切到 async-first，但结果查询客户端接口仍然保留同步风格")
    print("💡 生产黄金法则: 设置 result_expires + 不需要结果的任务用 ignore_result=True")


if __name__ == "__main__":
    asyncio.run(main())
