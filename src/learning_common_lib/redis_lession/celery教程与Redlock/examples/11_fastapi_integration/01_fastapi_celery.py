"""
目标: 演示 FastAPI + async-first Celery 集成 (FastAPI + custom aio pool)
关键概念:
  - worker 侧主线是 `custom aio pool + async def task`
  - FastAPI 发布任务和查询状态仍然通过 producer/result 客户端兼容层完成
  - HTTP 请求立即返回任务 ID，客户端轮询获取结果
关键 API: FastAPI, TestClient, AsyncResult, asyncio.to_thread
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/11_fastapi_integration
运行方式:
  Worker:
    CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool' \
    celery -A examples.11_fastapi_integration.01_fastapi_celery worker -l info -P custom -Q aio_fastapi -c 20
  Client:
    python examples/11_fastapi_integration/01_fastapi_celery.py
预期现象:
  - POST 请求立即返回 task_id
  - worker 侧执行 async def task
  - GET 轮询任务状态，从 PENDING 变为 SUCCESS
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from celery import Celery
from celery.result import AsyncResult
from fastapi import FastAPI
from starlette.testclient import TestClient

MODULE = "examples.11_fastapi_integration.01_fastapi_celery"

celery_app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
celery_app.conf.update(
    task_default_queue="aio_fastapi",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)


@celery_app.task(bind=True, name=f"{MODULE}.process_order")
async def process_order(self: Any, order_id: int, items: list[str]) -> dict[str, Any]:
    await asyncio.sleep(3)
    return {
        "order_id": order_id,
        "items": items,
        "status": "completed",
        "total": len(items) * 99.9,
        "task_shape": "async def",
    }


@celery_app.task(bind=True, name=f"{MODULE}.send_notification")
async def send_notification(self: Any, user_id: int, message: str) -> dict[str, Any]:
    await asyncio.sleep(2)
    return {"user_id": user_id, "status": "sent", "message": message, "task_shape": "async def"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("  🟢 FastAPI 启动，async-first Celery 连接就绪")
    yield
    print("  🔴 FastAPI 关闭")


api = FastAPI(title="Celery Demo API", lifespan=lifespan)


@api.post("/tasks/orders")
async def create_order_task(order_id: int, items: list[str]) -> dict[str, str]:
    result = await asyncio.to_thread(process_order.delay, order_id, items)
    return {
        "task_id": result.id,
        "status": "submitted",
        "message": f"订单 {order_id} 已提交处理",
    }


@api.post("/tasks/notifications")
async def create_notification_task(user_id: int, message: str) -> dict[str, str]:
    result = await asyncio.to_thread(send_notification.delay, user_id, message)
    return {"task_id": result.id, "status": "submitted"}


@api.get("/tasks/{task_id}")
async def get_task_status(task_id: str) -> dict[str, Any]:
    result = AsyncResult(task_id, app=celery_app)
    status = await asyncio.to_thread(lambda: result.status)
    ready = await asyncio.to_thread(result.ready)
    response: dict[str, Any] = {
        "task_id": task_id,
        "status": status,
        "ready": ready,
    }
    if ready:
        if await asyncio.to_thread(result.successful):
            response["result"] = await asyncio.to_thread(lambda: result.result)
        else:
            response["error"] = await asyncio.to_thread(lambda: str(result.result))
    return response


async def main() -> None:
    print("🚀 FastAPI + async-first Celery 集成示例\n")

    with TestClient(api) as client:
        print("── 步骤 1: POST 提交订单任务 ──")
        resp = client.post(
            "/tasks/orders",
            params={"order_id": 1001},
            json=["笔记本电脑", "机械键盘", "显示器"],
        )
        order_data = resp.json()
        print(f"  📥 响应 [{resp.status_code}]: {order_data}")
        task_id = order_data["task_id"]
        print()

        print("── 步骤 2: GET 轮询任务状态 ──")
        for i in range(30):
            resp2 = client.get(f"/tasks/{task_id}")
            status_data = resp2.json()
            if status_data.get("ready"):
                break
            print(f"  🔄 第 {i + 1} 次轮询, [{resp2.status_code}]: {status_data}")
            await asyncio.sleep(0.5)
        print(f"  📥 响应 [{resp2.status_code}]: {status_data}")
        print()

        print("── 步骤 3: POST 提交通知任务 ──")
        resp3 = client.post(
            "/tasks/notifications",
            params={"user_id": 42, "message": "您的订单已发货"},
        )
        notif_data = resp3.json()
        print(f"  📥 响应 [{resp3.status_code}]: {notif_data}")
        notif_task_id = notif_data["task_id"]
        print()

        print("── 步骤 4: GET 轮询通知状态 ──")
        for i in range(30):
            resp4 = client.get(f"/tasks/{notif_task_id}")
            notif_status = resp4.json()
            if notif_status.get("ready"):
                break
            print(f"  🔄 第 {i + 1} 次轮询, [{resp4.status_code}]: {notif_status}")
            await asyncio.sleep(0.5)
        print(f"  📥 响应 [{resp4.status_code}]: {notif_status}")
        print()

        print("── 步骤 5: 查询不存在的任务 ──")
        resp5 = client.get("/tasks/nonexistent-id-12345")
        print(f"  📥 响应 [{resp5.status_code}]: {resp5.json()}")
        print()

    print("── 生产部署架构 ──")
    print("  💡 FastAPI:  uvicorn myproj.api:app --host 0.0.0.0 --port 8000")
    print("  💡 Worker:   CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool' celery -A myproj.celery_app:app worker -P custom -Q aio_jobs --loglevel=info -c 20")
    print("  💡 Beat:     celery -A myproj.celery_app:app beat --loglevel=info")
    print("  💡 Flower:   celery -A myproj.celery_app:app flower --port=5555")


if __name__ == "__main__":
    asyncio.run(main())
