"""
目标: FastAPI + Celery 集成 — REST API 触发异步任务并轮询状态
关键 API: FastAPI, TestClient, lifespan, AsyncResult
Python 版本: 3.11+
运行命令:
  终端 1 (启动 Worker):
    celery -A examples.10_fastapi_integration.01_fastapi_celery worker -l info -P solo
  终端 2 (运行示例):
    uv run python examples/10_fastapi_integration/01_fastapi_celery.py
  (从 src/learning_common_lib/redis_lession/celery教程与Redlock 目录)
预期现象: TestClient 提交任务到真实 broker，worker 处理后客户端轮询获取结果
生产提醒: 生产环境需启动独立 worker 进程
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any

from celery import Celery
from celery.result import AsyncResult
from fastapi import FastAPI
from starlette.testclient import TestClient

# ── 1. 创建 Celery 应用 ──
celery_app = Celery(
    "examples.10_fastapi_integration.01_fastapi_celery",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)


# ── 2. 定义 Celery 任务 ──
@celery_app.task(bind=True)
def process_order(self: Any, order_id: int, items: list[str]) -> dict[str, Any]:
    """处理订单 — 模拟耗时操作"""
    print(f"  ⚙️ 处理订单: order_id={order_id}, items={items}")
    # 生产环境中这里可能耗时数秒
    return {
        "order_id": order_id,
        "items": items,
        "status": "completed",
        "total": len(items) * 99.9,
    }


@celery_app.task
def send_notification(user_id: int, message: str) -> dict[str, str]:
    """发送通知"""
    print(f"  📧 发送通知: user_id={user_id}, message={message}")
    return {"user_id": user_id, "status": "sent"}


# ── 3. 创建 FastAPI 应用 ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    print("  🟢 FastAPI 启动，Celery 连接就绪")
    yield
    print("  🔴 FastAPI 关闭")

api = FastAPI(title="Celery Demo API", lifespan=lifespan)


@api.post("/tasks/orders")
async def create_order_task(order_id: int, items: list[str]) -> dict[str, str]:
    """提交订单处理任务"""
    result = await asyncio.to_thread(
        process_order.delay, order_id, items,
    )
    return {
        "task_id": result.id,
        "status": "submitted",
        "message": f"订单 {order_id} 已提交处理",
    }


@api.post("/tasks/notifications")
async def create_notification_task(user_id: int, message: str) -> dict[str, str]:
    """提交通知发送任务"""
    result = await asyncio.to_thread(
        send_notification.delay, user_id, message,
    )
    return {"task_id": result.id, "status": "submitted"}


@api.get("/tasks/{task_id}")
async def get_task_status(task_id: str) -> dict[str, Any]:
    """轮询任务状态"""
    result = AsyncResult(task_id, app=celery_app)
    response: dict[str, Any] = {
        "task_id": task_id,
        "status": result.status,
        "ready": result.ready(),
    }
    if result.ready():
        if result.successful():
            response["result"] = result.get()
        else:
            response["error"] = str(result.result)
    return response


# ── 4. 入口: 使用 TestClient 模拟完整流程 ──
async def main() -> None:
    print("🚀 FastAPI + Celery 集成示例\n")

    with TestClient(api) as client:
        # 提交订单任务
        print("── 步骤 1: POST 提交订单任务 ──")
        resp = client.post(
            "/tasks/orders",
            params={"order_id": 1001},
            json=["笔记本电脑", "机械键盘", "显示器"],
        )
        order_data = resp.json()
        print(f"  📤 请求: POST /tasks/orders?order_id=1001")
        print(f"  📥 响应 [{resp.status_code}]: {order_data}")
        task_id = order_data["task_id"]
        print()

        # 轮询任务状态 (等待 worker 处理)
        print("── 步骤 2: GET 轮询任务状态 ──")
        for _ in range(30):
            resp2 = client.get(f"/tasks/{task_id}")
            status_data = resp2.json()
            if status_data.get("ready"):
                break
            time.sleep(0.5)
        print(f"  📤 请求: GET /tasks/{task_id}")
        print(f"  📥 响应 [{resp2.status_code}]: {status_data}")
        print()

        # 提交通知任务
        print("── 步骤 3: POST 提交通知任务 ──")
        resp3 = client.post(
            "/tasks/notifications",
            params={"user_id": 42, "message": "您的订单已发货"},
        )
        notif_data = resp3.json()
        print(f"  📤 请求: POST /tasks/notifications")
        print(f"  📥 响应 [{resp3.status_code}]: {notif_data}")
        notif_task_id = notif_data["task_id"]
        print()

        # 轮询通知任务 (等待 worker 处理)
        print("── 步骤 4: GET 轮询通知状态 ──")
        for _ in range(30):
            resp4 = client.get(f"/tasks/{notif_task_id}")
            notif_status = resp4.json()
            if notif_status.get("ready"):
                break
            time.sleep(0.5)
        print(f"  📤 请求: GET /tasks/{notif_task_id}")
        print(f"  📥 响应 [{resp4.status_code}]: {notif_status}")
        print()

        # 查询不存在的任务
        print("── 步骤 5: 查询不存在的任务 ──")
        resp5 = client.get("/tasks/nonexistent-id-12345")
        print(f"  📤 请求: GET /tasks/nonexistent-id-12345")
        print(f"  📥 响应 [{resp5.status_code}]: {resp5.json()}")
        print()

    # 生产部署说明
    print("── 生产部署架构 ──")
    print("  💡 FastAPI:  uvicorn app:api --host 0.0.0.0 --port 8000")
    print("  💡 Worker:   celery -A app worker --loglevel=info -c 4")
    print("  💡 Beat:     celery -A app beat --loglevel=info")
    print("  💡 Flower:   celery -A app flower --port=5555")


if __name__ == "__main__":
    asyncio.run(main())
