"""
解决什么问题: 提供 FastAPI + TaskIQ 集成的标准模式，包含 lifespan 管理、依赖注入、任务发送辅助
输入输出约定: taskiq_lifespan() 作为 FastAPI lifespan context manager；get_broker() 作为 FastAPI Depends；send_task() 发送任务并返回统一响应
失败策略: broker.startup() 失败时 FastAPI 启动失败；send_task() 异常返回错误响应
不适用场景: 不使用 FastAPI 的项目无需此模块
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

try:
    from fastapi import FastAPI, Depends  # noqa: F401
except ImportError:
    FastAPI = None  # type: ignore[assignment,misc]
    Depends = None  # type: ignore[assignment]

try:
    from pydantic import BaseModel
except ImportError:
    BaseModel = None  # type: ignore[assignment,misc]

try:
    from .taskiq_app import get_broker as _get_broker, init_broker
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.taskiq_app import get_broker as _get_broker, init_broker  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic 响应模型
# ---------------------------------------------------------------------------


if BaseModel is not None:
    class TaskResponse(BaseModel):
        """任务发送响应模型。

        字段:
            task_id: TaskIQ 返回的任务唯一标识
            status: 任务状态，发送成功时为 "queued"，失败时为 "error"
        """
        task_id: str
        status: str


# ---------------------------------------------------------------------------
# Lifespan 管理
# ---------------------------------------------------------------------------


@asynccontextmanager
async def taskiq_lifespan(app: Any) -> AsyncIterator[None]:
    """FastAPI lifespan context manager，管理 TaskIQ Broker 生命周期。

    进入时调用 broker.startup()，退出时调用 broker.shutdown()。
    如果 broker.startup() 失败，FastAPI 将无法启动。

    用法:
        app = FastAPI(lifespan=taskiq_lifespan)
    """
    broker = init_broker()
    logger.info("TaskIQ Broker 启动中...")
    await broker.startup()
    logger.info("TaskIQ Broker 启动完成")
    try:
        yield
    finally:
        logger.info("TaskIQ Broker 关闭中...")
        await broker.shutdown()
        logger.info("TaskIQ Broker 已关闭")


# ---------------------------------------------------------------------------
# FastAPI 依赖注入
# ---------------------------------------------------------------------------


async def get_broker() -> Any:
    """FastAPI 依赖项，返回 TaskIQ Broker 单例。

    用法:
        @app.post("/tasks")
        async def create_task(broker = Depends(get_broker)):
            ...
    """
    return _get_broker()


# ---------------------------------------------------------------------------
# 任务发送辅助
# ---------------------------------------------------------------------------


async def send_task(task: Any, *args: Any, **kwargs: Any) -> dict[str, str]:
    """发送 TaskIQ 任务并返回统一响应字典。

    参数:
        task: TaskIQ 任务对象（通过 @broker.task 或 create_task 注册的任务）
        *args: 任务位置参数
        **kwargs: 任务关键字参数

    返回:
        {"task_id": "<id>", "status": "queued"} 成功时
        {"task_id": "",     "status": "error: <msg>"} 失败时
    """
    try:
        handle = await task.kiq(*args, **kwargs)
        logger.info("任务已发送: task=%s task_id=%s", task.task_name, handle.task_id)
        return {"task_id": handle.task_id, "status": "queued"}
    except Exception as exc:
        logger.error("任务发送失败: task=%s error=%s", getattr(task, "task_name", "?"), exc, exc_info=True)
        return {"task_id": "", "status": f"error: {exc}"}


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：FastAPI + TaskIQ 集成模式说明。"""
    print("=== FastAPI + TaskIQ 集成模式 ===")
    print()
    print("1. Lifespan 管理:")
    print("   from templates.fastapi_taskiq import taskiq_lifespan")
    print("   app = FastAPI(lifespan=taskiq_lifespan)")
    print()
    print("2. 依赖注入:")
    print("   from templates.fastapi_taskiq import get_broker")
    print("   @app.post('/tasks')")
    print("   async def create(broker=Depends(get_broker)):")
    print("       ...")
    print()
    print("3. 发送任务:")
    print("   from templates.fastapi_taskiq import send_task")
    print("   result = await send_task(my_task, arg1, arg2)")
    print("   # result = {'task_id': '...', 'status': 'queued'}")
    print()
    print("4. 响应模型:")
    if BaseModel is not None:
        resp = TaskResponse(task_id="abc-123", status="queued")
        print(f"   TaskResponse 示例: {resp.model_dump()}")
    else:
        print("   (pydantic 未安装，TaskResponse 不可用)")
    print()
    print("✅ fastapi_taskiq 模块演示完成")


if __name__ == "__main__":
    _demo()
