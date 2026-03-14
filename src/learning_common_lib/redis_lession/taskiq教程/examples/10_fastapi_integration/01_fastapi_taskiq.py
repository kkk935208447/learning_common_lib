"""
FastAPI + TaskIQ 集成 — lifespan 管理、API 端点发送任务、查询结果。

目标:
    演示 FastAPI + TaskIQ 集成 — lifespan 管理、API 端点发送任务、查询结果

关键概念:
    - FastAPI lifespan 中调用 broker.startup() / broker.shutdown()
    - API 端点发送任务并返回 task_id
    - 查询端点获取任务结果
    - 无需 taskiq-fastapi 包，手动集成更灵活

关键 API:
    - FastAPI lifespan                 — 应用生命周期管理
    - broker.startup() / shutdown()    — Broker 初始化和清理
    - task.kiq()                       — 发送任务
    - result_backend.get_result()      — 查询任务结果

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/10_fastapi_integration

运行方式:
    Worker:
        taskiq worker examples.10_fastapi_integration.01_fastapi_taskiq:broker
    Server:
        uvicorn examples.10_fastapi_integration.01_fastapi_taskiq:app --reload
    (注意: 请手动在终端启动 uvicorn，不要在脚本中启动)

预期现象:
    - POST /tasks/process-order 返回 {"task_id": "...", "status": "queued"}
    - GET /tasks/{task_id} 返回任务执行结果或等待状态
    - Worker 控制台显示订单处理日志

生产提醒:
    - lifespan context manager 确保 broker 正确初始化和清理
    - 统一响应格式便于前端处理
    - 查询结果时注意超时和异常处理

技术要点:
    - lifespan context manager 确保 broker 正确初始化和清理
    - 统一响应格式：{"task_id": "...", "status": "queued"}
    - 查询结果时使用 result_backend 直接查询
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from taskiq.exceptions import ResultBackendError
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend
from taskiq_redis.exceptions import ResultIsMissingError

QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:examples:10_fastapi_integration:01_fastapi_taskiq",
)

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
).with_result_backend(result_backend)


# ── 2. 定义异步任务 ──


@broker.task(task_name="examples.10_fastapi_integration.01_fastapi_taskiq.process_order")
async def process_order(order_id: int, amount: float) -> dict:
    """处理订单 — 模拟耗时业务逻辑。"""
    import random

    print(f"📦 Worker 处理订单: order_id={order_id}, amount={amount}")
    # 模拟耗时操作
    await asyncio.sleep(random.uniform(1.0, 3.0))
    result = {
        "order_id": order_id,
        "amount": amount,
        "status": "completed",
        "message": f"订单 {order_id} 处理成功",
    }
    print(f"✅ 订单处理完成: {result}")
    return result


# ── 3. FastAPI lifespan — 管理 Broker 生命周期 ──


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期管理 — 启动时初始化 broker，关闭时清理。"""
    print("🚀 FastAPI 启动: 初始化 TaskIQ broker...")
    await broker.startup()
    print("✅ TaskIQ broker 已就绪")
    yield
    print("🛑 FastAPI 关闭: 清理 TaskIQ broker...")
    await broker.shutdown()
    print("✅ TaskIQ broker 已关闭")


app = FastAPI(
    title="TaskIQ + FastAPI 集成示例",
    lifespan=lifespan,
)


# ── 4. API 端点 ──


@app.post("/tasks/process-order")
async def create_order_task(order_id: int, amount: float) -> dict:
    """发送订单处理任务，返回 task_id。"""
    handle = await process_order.kiq(order_id=order_id, amount=amount)
    return {
        "task_id": handle.task_id,
        "status": "queued",
        "message": f"订单 {order_id} 已提交处理",
    }


@app.get("/tasks/{task_id}")
async def get_task_result(task_id: str) -> dict:
    """查询任务结果 — 通过 result_backend 直接查询。"""
    try:
        result = await result_backend.get_result(task_id)
        if result.is_err:
            return {
                "task_id": task_id,
                "status": "error",
                "error": str(result.error),
            }
        return {
            "task_id": task_id,
            "status": "completed",
            "result": result.return_value,
        }
    except ResultIsMissingError:
        return {
            "task_id": task_id,
            "status": "pending",
            "message": "任务结果尚未写入，可能仍在执行，或 task_id 不存在",
        }
    except ResultBackendError as exc:
        return {
            "task_id": task_id,
            "status": "backend_error",
            "message": f"结果后端查询失败: {exc}",
        }


# ── 5. 脚本入口 — 打印启动说明 ──


async def main() -> None:
    """打印启动说明和测试命令（不实际启动 uvicorn）。"""
    print("=" * 60)
    print("🚀 FastAPI + TaskIQ 集成示例")
    print("=" * 60)
    print()
    print("📋 启动步骤:")
    print()
    print("  1️⃣  启动 Worker（处理任务）:")
    print("     taskiq worker examples.10_fastapi_integration.01_fastapi_taskiq:broker")
    print()
    print("  2️⃣  启动 FastAPI 服务（接收请求）:")
    print("     uvicorn examples.10_fastapi_integration.01_fastapi_taskiq:app --reload")
    print()
    print("📋 测试命令 (curl):")
    print()
    print("  # 发送订单处理任务")
    print('  curl -X POST "http://127.0.0.1:8000/tasks/process-order?order_id=1001&amount=99.9"')
    print()
    print("  # 查询任务结果（替换 <task_id>）")
    print('  curl "http://127.0.0.1:8000/tasks/<task_id>"')
    print()
    print("💡 架构说明:")
    print("  Client → FastAPI → broker.kiq() → Redis → Worker → result_backend")
    print("  Client → FastAPI → result_backend.get_result() ← Redis")
    print()
    print("💡 关键点:")
    print("  - lifespan 确保 broker 在 FastAPI 启动/关闭时正确初始化和清理")
    print("  - 无需 taskiq-fastapi 包，手动集成更灵活、更透明")
    print("  - 统一响应格式: {\"task_id\": \"...\", \"status\": \"queued/completed/error\"}")


if __name__ == "__main__":
    asyncio.run(main())
