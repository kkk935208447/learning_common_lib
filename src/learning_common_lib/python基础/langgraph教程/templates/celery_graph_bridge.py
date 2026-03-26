"""LangGraph + Celery 桥接：在图节点内安全地分发 Celery 任务。

模板层只提供“分发契约”和“恢复契约”的最小骨架：
- 图内只 dispatch，不等待 `.get()`
- 外部 worker 回写 `ResumeEnvelope`
- 恢复器先判定 accepted / stale，再恢复图执行
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, TypedDict

from celery import Celery

try:
    from .runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings
    from .teaching_contracts import ExecutionRef, ResumeEnvelope
except ImportError:  # pragma: no cover - 允许直接运行模板文件
    from runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings
    from teaching_contracts import ExecutionRef, ResumeEnvelope

logger = logging.getLogger(__name__)
_SETTINGS: RedisRuntimeSettings = DEFAULT_RUNTIME_SETTINGS


class DispatchEnvelope(TypedDict, total=False):
    task_id: str
    thread_id: str
    execution_id: str
    queue: str
    task_name: str
    status: str
    plan_version: int | None
    subtask_code: str | None


class ResumeDecision(TypedDict):
    accepted: bool
    status: str
    stale_reason: str | None

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
        "status": "DISPATCHED",
        "plan_version": None,
        "subtask_code": None,
    }


def build_execution_ref(
    *,
    thread_id: str,
    execution_id: str,
    task_name: str,
    plan_version: int | None = None,
    subtask_code: str | None = None,
) -> ExecutionRef:
    """构造等待恢复时的执行引用。"""
    return {
        "thread_id": thread_id,
        "execution_id": execution_id,
        "task_name": task_name,
        "plan_version": plan_version or 0,
        "subtask_code": subtask_code,
    }


def accept_or_mark_stale(
    result: ResumeEnvelope,
    *,
    current_execution_id: str,
) -> ResumeDecision:
    """最小 stale result fencing。

    教程里的真实版示例会在更高层补 `plan_version/subtask_code` 校验，
    模板先固定最小可复用的 execution_id 判定。
    """
    if result.get("execution_id") != current_execution_id:
        return {
            "accepted": False,
            "status": "STALE_IGNORED",
            "stale_reason": (
                f"result.execution_id={result.get('execution_id')} "
                f"!= current_execution_id={current_execution_id}"
            ),
        }
    return {
        "accepted": True,
        "status": result.get("status", "COMPLETED"),
        "stale_reason": None,
    }


# ---------------------------------------------------------------------------
# Celery -> 图 恢复
# ---------------------------------------------------------------------------

async def resume_orchestrator_async(
    result: ResumeEnvelope,
    *,
    current_execution_id: str | None = None,
) -> dict[str, Any]:
    """异步恢复编排器（由 Celery 任务回调触发）。

    实际项目中会：
    1. 先把结果写回控制面
    2. 做 accepted/stale 判定
    3. 追加 task_event
    4. 用同一 thread_id 恢复图
    """
    logger.info("恢复编排器，收到结果: %s", result)
    decision: ResumeDecision | None = None
    if current_execution_id is not None:
        decision = accept_or_mark_stale(result, current_execution_id=current_execution_id)
        logger.info("恢复判定: %s", decision)
    return {
        "status": "resumed",
        "result": result,
        "decision": decision,
    }


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
    print("  dispatch_to_celery: 返回 DISPATCHED envelope")
    print("  accept_or_mark_stale: 用 execution_id 做最小 fencing")
    print("  resume_orchestrator: Celery 回调恢复图执行")
    print("  注意: 实际运行需要 Redis 和 Celery worker")


if __name__ == "__main__":
    _demo()
