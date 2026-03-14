"""
目标: 演示 custom aio pool 下真正的 async def task (Custom AsyncIO Pool)
关键概念:
  - custom aio pool 把 worker 执行层接到 asyncio event loop
  - async def task 可以真正 await 协程和异步 IO
  - producer 边界不变：delay/get 仍然是 Celery 同步 API
关键 API: CELERY_CUSTOM_WORKER_POOL, -P custom, @app.task, asyncio.gather, httpx.AsyncClient
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/04_async_worker_tasks
运行方式:
  Worker:
    export CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool'
    celery -A examples.04_async_worker_tasks.03_custom_aio_pool_async_task worker -l info -P custom -c 20 -Q aio_jobs
  Client:
    python examples/04_async_worker_tasks/03_custom_aio_pool_async_task.py
预期现象:
  - async def task 在 worker 中被真正 await
  - task 内部可以直接 asyncio.gather() 组合多个异步步骤
  - producer 侧依旧需要 asyncio.to_thread() 包装 Celery API
生产提醒:
  - 这是 Celery 接入 asyncio 的方式，不等于 Celery 客户端 API 也变成了 async
  - 只有真正使用异步库的任务才值得放进 aio worker
技术要点:
  - 这里使用 httpx.MockTransport，避免依赖外部网络
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from celery import Celery

MODULE = "examples.04_async_worker_tasks.03_custom_aio_pool_async_task"

app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.task_default_queue = "aio_jobs"


def print_section(title: str) -> None:
    print(f"── {title} ──")


def _mock_order_service(request: httpx.Request) -> httpx.Response:
    order_id = request.url.params.get("order_id", "unknown")
    return httpx.Response(200, json={"order_id": order_id, "status": "ready"})


def _mock_metrics_service(request: httpx.Request) -> httpx.Response:
    order_id = request.url.params.get("order_id", "unknown")
    return httpx.Response(200, json={"order_id": order_id, "items": 3, "amount": 299.0})


async def fetch_order_parts(order_id: str) -> dict[str, Any]:
    order_transport = httpx.MockTransport(_mock_order_service)
    metrics_transport = httpx.MockTransport(_mock_metrics_service)
    async with httpx.AsyncClient(
        transport=order_transport,
        base_url="https://order.local",
        timeout=5.0,
    ) as order_client, httpx.AsyncClient(
        transport=metrics_transport,
        base_url="https://metrics.local",
        timeout=5.0,
    ) as metrics_client:
        order_response, metrics_response = await asyncio.gather(
            order_client.get("/orders", params={"order_id": order_id}),
            metrics_client.get("/metrics", params={"order_id": order_id}),
        )
    return {
        "summary": order_response.json(),
        "metrics": metrics_response.json(),
    }


@app.task(bind=True, name=f"{MODULE}.fetch_order_async")
async def fetch_order_async(self: Any, order_id: str) -> dict[str, Any]:
    started = asyncio.get_running_loop().time()
    await asyncio.sleep(0.2)
    payload = await fetch_order_parts(order_id)
    payload.update(
        {
            "task_id": self.request.id,
            "task_shape": "async def",
            "worker_pool": "custom aio pool",
            "elapsed_s": round(asyncio.get_running_loop().time() - started, 3),
        }
    )
    return payload


async def main() -> None:
    print("🚀 custom aio pool 示例：真正的 async def task\n")

    print_section("场景 A: async def task 直接 await 多个异步步骤")
    result = await asyncio.to_thread(fetch_order_async.delay, "ORD-AIO-2001")
    payload = await asyncio.to_thread(result.get, timeout=30)
    print(f"  ✅ {payload}")
    print("  结论: 这次 worker 侧真正执行的是 async def task，而不是 sync def + 桥接。\n")

    print_section("场景 B: producer 侧边界并没有改变")
    print("  发布任务: asyncio.to_thread(fetch_order_async.delay, ...)")
    print("  取回结果: asyncio.to_thread(result.get, timeout=30)")
    print("  结论: aio pool 改的是 worker 执行层，不是 Celery 客户端 API。\n")

    print_section("这一层与上一层的区别")
    summary_rows = [
        ("gevent", "sync def", "官方 greenlet 并发池"),
        ("custom aio pool", "async def", "原生 asyncio event loop"),
        ("producer 调用", "仍是同步 API", "需要 to_thread 包装"),
    ]
    for label, value, note in summary_rows:
        print(f"  {label:<16} {value:<18} {note}")


if __name__ == "__main__":
    asyncio.run(main())
