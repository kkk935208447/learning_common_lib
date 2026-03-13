"""
目标: 演示结果过期配置与生命周期管理 (Result Expiry & Lifecycle)
关键 API: result_expires, result_extended, AsyncResult.forget()
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
运行方式:
  Worker: celery -A examples.04_result_backend.02_result_expiry worker -l info
  Client: python examples/04_result_backend/02_result_expiry.py
预期现象: 展示结果过期配置、扩展元数据、手动清理效果
生产提醒: 务必设置 result_expires，否则 Redis/DB 会无限膨胀
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from celery import Celery
from celery.result import AsyncResult

# ── 1. 创建应用 (秒数方式设置过期) ──
app = Celery(
    "examples.04_result_backend.02_result_expiry",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.update(
    result_expires=3600,       # 结果保留 1 小时 (秒)
    result_extended=True,      # 启用扩展结果元数据
)


@app.task(bind=True)
def slow_add(self, x: int, y: int) -> int:
    print(f"  📦 slow_add({x}, {y}) task_id={self.request.id}")
    return x + y


@app.task(bind=True, ignore_result=True)
def notify(self, msg: str) -> None:
    print(f"  📦 notify: {msg} (结果不存储)")


# ── 2. 入口 ──
async def main() -> None:
    print("🚀 结果过期与扩展元数据示例\n")

    # ── result_expires 配置方式 ──
    print("── result_expires 配置方式 ──")

    # 方式一: 整数秒
    print(f"  当前配置 (秒): result_expires = {app.conf.result_expires}")

    # 方式二: timedelta (演示如何设置)
    # ⚠️ 运行时修改只影响当前进程，已启动的 worker 不受影响
    app.conf.result_expires = timedelta(hours=2)
    print(f"  修改为 timedelta: result_expires = {app.conf.result_expires}")

    # 方式三: 禁用过期 (不推荐)
    print(f"  💡 设为 None 可禁用过期 (不推荐，会导致存储膨胀)")

    # 恢复为秒数
    app.conf.result_expires = 3600
    print()

    # ── 结果生命周期 ──
    print("── 结果生命周期 ──")
    r1 = await asyncio.to_thread(slow_add.delay, 10, 20)
    task_id = r1.id

    # 阶段 1: 结果可用
    print(f"  阶段 1 - 结果可用:")
    val1 = await asyncio.to_thread(r1.get, timeout=30)
    print(f"    state: {r1.state}")
    print(f"    result: {val1}")
    print(f"    ready: {r1.ready()}")

    # 阶段 2: 手动清理
    print(f"  阶段 2 - forget() 手动清理:")
    r1.forget()
    r1_check = AsyncResult(task_id, app=app)
    print(f"    清理后 state: {r1_check.state}")
    print(f"    💡 forget() 立即删除，不等过期时间")
    print()

    # ── result_extended 扩展元数据 ──
    print("── result_extended=True 扩展元数据 ──")
    print(f"  配置: result_extended = {app.conf.result_extended}")

    r2 = await asyncio.to_thread(slow_add.delay, 100, 200)
    r2_val = await asyncio.to_thread(r2.get, timeout=30)  # 先等待任务完成
    result_meta: dict[str, Any] = {
        "id": r2.id,
        "state": r2.state,
        "result": r2_val,
    }

    # 扩展字段 (result_extended=True 时可用)
    extended_attrs = ["name", "args", "kwargs", "worker", "queue"]
    for attr in extended_attrs:
        val = getattr(r2, attr, "N/A")
        result_meta[attr] = val

    print(f"  扩展元数据:")
    for k, v in result_meta.items():
        print(f"    {k:.<20} {v!r}")
    print()

    # ── ignore_result 与过期的关系 ──
    print("── ignore_result 与过期 ──")
    r3 = await asyncio.to_thread(notify.delay, "用户注册成功")
    print(f"  ignore_result=True 的任务:")
    print(f"    state: {r3.state}")
    print(f"    💡 ignore_result=True 的任务不写入 backend，无需担心过期")
    print()

    # ── 最佳实践 ──
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

    # ── 不同 backend 的过期行为 ──
    print("── 不同 backend 的过期机制 ──")
    backends: list[tuple[str, str]] = [
        ("Redis", "利用 Redis TTL 自动过期，最高效"),
        ("Database", "需要定期运行 celery beat + DatabaseCleanup"),
        ("RPC (AMQP)", "结果作为消息，消费后自动删除"),
        ("Filesystem", "需要自行清理文件"),
    ]
    for backend, mechanism in backends:
        print(f"  📋 {backend:.<15} {mechanism}")

    print("\n💡 生产黄金法则: 设置 result_expires + 不需要结果的任务用 ignore_result=True")


if __name__ == "__main__":
    asyncio.run(main())
