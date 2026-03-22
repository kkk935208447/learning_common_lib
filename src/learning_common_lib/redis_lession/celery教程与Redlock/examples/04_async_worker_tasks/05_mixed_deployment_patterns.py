"""
目标: 演示 sync task 与 async task 在同一项目中的混合部署 (Mixed Deployment)
关键概念:
  - 同一个项目里可以同时保留 prefork 队列和 aio 队列
  - greenlet 路线可以作为中间车道单独部署，但不必强行和 aio demo 混成一个实跑脚本
  - 真正稳定的做法是按任务类型拆 lane
关键 API: task_routes, queue, time.sleep, async def task, CELERY_CUSTOM_WORKER_POOL
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/04_async_worker_tasks
运行方式:
  Worker 1 (prefork):
    celery -A examples.04_async_worker_tasks.05_mixed_deployment_patterns worker -l info -P prefork -c 2 -Q prefork_jobs
  Worker 2 (custom aio pool):
    export CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool'
    celery -A examples.04_async_worker_tasks.05_mixed_deployment_patterns worker -l info -P custom -c 20 -Q aio_jobs
  Client:
    python examples/04_async_worker_tasks/05_mixed_deployment_patterns.py
预期现象:
  - render_invoice 走 prefork 队列
  - push_webhook_async 走 aio 队列
  - greenlet lane 不在本文件实跑，但会在部署矩阵里作为官方中间态给出位置
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from celery import Celery

MODULE = "examples.04_async_worker_tasks.05_mixed_deployment_patterns"

app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.update(
    # 这里故意不显式写 task_queues / Exchange / routing_key。这个示例的重点不是讲完整消息拓扑，而是讲“同一项目按任务形态拆 worker lane”。
    # 对当前 Redis + 简单双队列 demo 来说，只指定 queue 名已经足够表达：
    #   1. render_invoice 默认走 prefork_jobs
    #   2. push_webhook_async 自动路由到 aio_jobs
    # 真要讲清 exchange / routing_key / 多队列绑定关系，请看 07 章的 01_task_queues.py。
    task_default_queue="prefork_jobs",
    task_routes={
        f"{MODULE}.render_invoice": {"queue": "prefork_jobs"},
        f"{MODULE}.push_webhook_async": {"queue": "aio_jobs"},
    },
)


def print_section(title: str) -> None:
    print(f"── {title} ──")


def _mock_webhook(request: httpx.Request) -> httpx.Response:
    return httpx.Response(202, json={"accepted": True, "path": str(request.url.path)})


@app.task(bind=True, name=f"{MODULE}.render_invoice")
def render_invoice(self: Any, order_id: str) -> dict[str, Any]:
    time.sleep(0.6)
    return {
        "task_id": self.request.id,
        "task_name": "render_invoice",
        "queue": "prefork_jobs",
        "worker_pool": "prefork",
        "task_shape": "sync def",
        "order_id": order_id,
    }


@app.task(bind=True, name=f"{MODULE}.push_webhook_async")
async def push_webhook_async(self: Any, order_id: str) -> dict[str, Any]:
    transport = httpx.MockTransport(_mock_webhook)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://hooks.local",
        timeout=5.0,
    ) as client:
        response = await client.post(f"/orders/{order_id}")
    return {
        "task_id": self.request.id,
        "task_name": "push_webhook_async",
        "queue": "aio_jobs",
        "worker_pool": "custom aio pool",
        "task_shape": "async def",
        "order_id": order_id,
        "payload": response.json(),
    }


async def main() -> None:
    print("🚀 一个项目中混合部署 prefork + aio worker\n")

    print_section("场景 A: 同一业务流程里的同步任务与异步任务")
    invoice_result, webhook_result = await asyncio.gather(
        asyncio.to_thread(render_invoice.delay, "ORD-MIX-1001"),
        asyncio.to_thread(push_webhook_async.delay, "ORD-MIX-1001"),
    )
    invoice_payload, webhook_payload = await asyncio.gather(
        asyncio.to_thread(invoice_result.get, timeout=30),
        asyncio.to_thread(webhook_result.get, timeout=30),
    )
    print(f"  ✅ {invoice_payload}")
    print(f"  ✅ {webhook_payload}\n")

    print_section("场景 B: 项目级部署矩阵")
    lanes = [
        ("prefork lane", "prefork_jobs", "sync def", "CPU / 阻塞式 SDK"),
        ("greenlet lane", "greenlet_jobs", "sync def", "官方 gevent 中间态，适合 cooperative IO"),
        ("aio lane", "aio_jobs", "async def", "原生 asyncio IO"),
    ]
    for lane, queue, task_shape, scenario in lanes:
        print(f"  {lane:<14} queue={queue:<14} task={task_shape:<10} {scenario}")
    print()

    print_section("部署结论")
    conclusions = [
        "sync task 与 async task 可以在同一项目中共存，但应拆到不同 worker lane。",
        "greenlet lane 是官方中间态，适合 cooperative IO，不必强塞进 aio demo 同跑。",
        "真正稳定的工程方式是按任务依赖模型拆队列、拆 worker 组。",
    ]
    for line in conclusions:
        print(f"  - {line}")


if __name__ == "__main__":
    asyncio.run(main())
