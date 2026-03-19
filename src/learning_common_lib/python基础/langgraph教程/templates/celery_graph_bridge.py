"""LangGraph + Celery 桥接：在图节点内安全地分发 Celery 任务。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, TypedDict

from celery import Celery

try:
    from .runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings
except ImportError:  # pragma: no cover - 允许直接运行模板文件
    from runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings

logger = logging.getLogger(__name__)
_SETTINGS: RedisRuntimeSettings = DEFAULT_RUNTIME_SETTINGS


class DispatchEnvelope(TypedDict, total=False):
    task_id: str
    thread_id: str
    execution_id: str
    queue: str
    task_name: str


class ResumeEnvelope(TypedDict, total=False):
    thread_id: str
    execution_id: str
    task_id: str
    result_ref: str | None
    result_payload: dict[str, Any] | None

# ---------------------------------------------------------------------------
# Celery 应用（示例配置）
# ---------------------------------------------------------------------------

celery_app = Celery(
    "langgraph_bridge",
    broker=_SETTINGS.celery_broker_url,
    backend=_SETTINGS.celery_backend_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
)


# ---------------------------------------------------------------------------
# 图 -> Celery 分发
# ---------------------------------------------------------------------------

async def dispatch_to_celery(
    task_name: str,
    args: dict[str, Any],
    queue: str = "default",
    *,
    thread_id: str | None = None,
    execution_id: str | None = None,
) -> DispatchEnvelope:
    """在图节点内安全地分发 Celery 任务（不阻塞事件循环）。

    返回 task_id，不调用 .get() 以避免死锁。
    """
    loop = asyncio.get_running_loop()
    task = await loop.run_in_executor(
        None,
        lambda: celery_app.send_task(task_name, kwargs=args, queue=queue),
    )
    logger.info(
        "已分发 Celery 任务 %s -> %s (queue=%s, thread_id=%s, execution_id=%s)",
        task_name,
        task.id,
        queue,
        thread_id,
        execution_id,
    )
    return {
        "task_id": task.id,
        "thread_id": thread_id or "",
        "execution_id": execution_id or "",
        "queue": queue,
        "task_name": task_name,
    }


# ---------------------------------------------------------------------------
# Celery -> 图 恢复
# ---------------------------------------------------------------------------

async def resume_orchestrator_async(result: ResumeEnvelope) -> dict[str, Any]:
    """异步恢复编排器（由 Celery 任务回调触发）。"""
    logger.info("恢复编排器，收到结果: %s", result)
    # 实际项目中：从 checkpoint 恢复图状态，注入 result，继续执行
    return {"status": "resumed", "result": result}


@celery_app.task(queue="orchestrate_jobs")
def resume_orchestrator(result: ResumeEnvelope) -> dict[str, Any]:
    """Celery 薄适配层：桥接同步 Celery worker 与异步图执行。"""
    return asyncio.run(resume_orchestrator_async(result))


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    """演示桥接模块的结构（不实际连接 Redis）。"""
    print("celery_graph_bridge 模块结构:")
    print(f"  Celery app: {celery_app.main}")
    print(f"  dispatch_to_celery: 返回 task_id/thread_id/execution_id 契约")
    print(f"  resume_orchestrator: Celery 回调恢复图执行")
    print("  注意: 实际运行需要 Redis 和 Celery worker")


if __name__ == "__main__":
    _demo()
