"""
目标: 建立 Celery 传统同步 worker 的基线认知 (Prefork Baseline for Sync Tasks)
关键概念:
  - async producer: async 路由或脚本可以用 asyncio.to_thread() 安全发布任务
  - sync worker: prefork worker 执行的仍然是普通 def task
  - 渐进桥接: 如果 task 里必须调用协程，可以显式 asyncio.run()
关键 API: asyncio.to_thread, asyncio.run, task.delay(), result.get()
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/04_async_worker_tasks
运行方式:
  Worker: celery -A examples.04_async_worker_tasks.01_sync_worker_baseline worker -l info -P prefork -c 2 -Q prefork_jobs
  Client: python examples/04_async_worker_tasks/01_sync_worker_baseline.py
预期现象:
  - async producer 不会阻塞事件循环
  - worker 侧执行的仍然是同步 def task
  - 桥接协程靠的是 task 内部的 asyncio.run()，不是 Celery 自动 await
生产提醒:
  - prefork 仍是 Celery 官方默认推荐的 worker pool
  - 阻塞式 SDK、CPU 任务、旧项目迁移都应先以这个基线为参照
技术要点:
  - 第 4 章后续所有对比，都是以这个 prefork 基线为起点
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from celery import Celery

MODULE = "examples.04_async_worker_tasks.01_sync_worker_baseline"

app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.task_default_queue = "prefork_jobs"


def print_section(title: str) -> None:
    print(f"── {title} ──")


@app.task(bind=True, name=f"{MODULE}.add_numbers")
def add_numbers(self: Any, x: int, y: int) -> dict[str, Any]:
    """传统同步 task：prefork worker 直接执行函数体。"""
    started = time.perf_counter()
    time.sleep(0.4)
    return {
        "task_id": self.request.id,
        "result": x + y,
        "task_shape": "sync def",
        "worker_pool": "prefork",
        "elapsed_s": round(time.perf_counter() - started, 3),
        "why_it_exists": "阻塞式逻辑直接放进 worker 子进程执行",
    }


async def fake_price_lookup(order_id: str) -> dict[str, Any]:
    """模拟 async IO，例如异步 HTTP / 异步数据库调用。"""
    await asyncio.sleep(0.3)
    return {
        "order_id": order_id,
        "price": 199.0,
        "source": "async coroutine",
    }


@app.task(bind=True, name=f"{MODULE}.bridge_async_lookup")
def bridge_async_lookup(self: Any, order_id: str) -> dict[str, Any]:
    """在同步 task 里显式桥接协程。"""
    started = time.perf_counter()
    payload = asyncio.run(fake_price_lookup(order_id))
    payload.update(
        {
            "task_id": self.request.id,
            "task_shape": "sync def + asyncio.run()",
            "worker_pool": "prefork",
            "elapsed_s": round(time.perf_counter() - started, 3),
            "why_it_exists": "迁移期复用 async 代码，但 worker 仍是同步模型",
        }
    )
    return payload


async def wait_result(label: str, async_result: Any) -> dict[str, Any]:
    payload = await asyncio.to_thread(async_result.get, timeout=30)
    print(f"  ✅ {label}: {payload}")
    return payload


async def main() -> None:
    print("🚀 prefork 基线示例：producer async 与 worker sync\n")

    print_section("场景 A: async producer 发布传统同步 task")
    add_result = await asyncio.to_thread(add_numbers.delay, 3, 7)
    await wait_result("prefork 同步 task", add_result)
    print("  结论: async producer 只是为了不阻塞调用方，worker 还是在执行普通 def task。\n")

    print_section("场景 B: 同步 task 内部手动桥接协程")
    bridge_result = await asyncio.to_thread(bridge_async_lookup.delay, "ORD-BASE-1001")
    await wait_result("prefork + asyncio.run()", bridge_result)
    print("  结论: 这里真正的 await 发生在 task 内部；Celery 本身并没有原生执行 async def。\n")

    print_section("基线总结")
    summary_rows = [
        ("producer 侧", "可以是 async", "用 asyncio.to_thread() 包装 Celery 同步 API"),
        ("worker 侧", "仍是 sync", "prefork 执行的是 def task"),
        ("迁移期中间态", "sync def + asyncio.run()", "适合少量复用 async 代码"),
        ("推荐场景", "默认首选", "CPU 任务、阻塞式 SDK、老代码迁移"),
    ]
    for label, value, note in summary_rows:
        print(f"  {label:<12} {value:<22} {note}")


if __name__ == "__main__":
    asyncio.run(main())
