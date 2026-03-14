"""
目标: 演示 FastAPI + Celery 集成与异步任务管理 (FastAPI + Celery Integration & Async Task Management)
关键概念:
  - Web 异步任务模式：HTTP 请求立即返回任务 ID，客户端轮询或推送获取结果
  - 应用生命周期管理：lifespan 确保 Celery 应用正确初始化和清理
  - 任务状态 API：RESTful 接口提供任务提交、状态查询、结果获取功能
关键 API: FastAPI, TestClient, AsyncResult, lifespan, asyncio.to_thread
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/11_fastapi_integration
运行方式:
  Worker: celery -A examples.11_fastapi_integration.01_fastapi_celery worker -l info
    (启动 worker 处理来自 FastAPI 的任务)
  Client: python examples/11_fastapi_integration/01_fastapi_celery.py
    (使用 TestClient 模拟 HTTP 请求和任务轮询)
预期现象:
  - POST 请求立即返回任务 ID，不阻塞 HTTP 响应
  - GET 请求轮询任务状态，从 PENDING 变为 SUCCESS
  - TestClient 演示完整的异步任务生命周期
生产提醒:
  - 生产环境建议将 Celery app 抽取到独立模块，便于 worker/beat/Flower 统一管理
  - 避免在 HTTP 请求处理中调用 result.get()，会阻塞整个 Web 服务
技术要点:
  - asyncio.to_thread() 将同步 Celery 调用包装为异步操作
  - lifespan 管理应用启动和关闭时的资源初始化
  - TestClient 提供同步接口测试异步 FastAPI 应用
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
    "examples.11_fastapi_integration.01_fastapi_celery",
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
            await asyncio.sleep(0.5)
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
            await asyncio.sleep(0.5)
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
    print("  💡 FastAPI:  uvicorn myproj.api:app --host 0.0.0.0 --port 8000")
    print("  💡 Worker:   celery -A myproj.celery_app:app worker --loglevel=info -c 4")
    print("  💡 Beat:     celery -A myproj.celery_app:app beat --loglevel=info")
    print("  💡 Flower:   celery -A myproj.celery_app:app flower --port=5555")


if __name__ == "__main__":
    asyncio.run(main())
