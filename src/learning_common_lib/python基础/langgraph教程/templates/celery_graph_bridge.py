"""LangGraph + Celery 桥接：在图节点内安全地分发 Celery 任务。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery import Celery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Celery 应用（示例配置）
# ---------------------------------------------------------------------------

celery_app = Celery(
    "langgraph_bridge",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/0",
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
) -> str:
    """在图节点内安全地分发 Celery 任务（不阻塞事件循环）。

    返回 task_id，不调用 .get() 以避免死锁。
    """
    loop = asyncio.get_running_loop()
    task = await loop.run_in_executor(
        None,
        lambda: celery_app.send_task(task_name, kwargs=args, queue=queue),
    )
    logger.info("已分发 Celery 任务 %s -> %s (queue=%s)", task_name, task.id, queue)
    return task.id


# ---------------------------------------------------------------------------
# Celery -> 图 恢复
# ---------------------------------------------------------------------------

async def resume_orchestrator_async(result: dict[str, Any]) -> dict[str, Any]:
    """异步恢复编排器（由 Celery 任务回调触发）。"""
    logger.info("恢复编排器，收到结果: %s", result)
    # 实际项目中：从 checkpoint 恢复图状态，注入 result，继续执行
    return {"status": "resumed", "result": result}


@celery_app.task(queue="orchestrate_jobs")
def resume_orchestrator(result: dict[str, Any]) -> dict[str, Any]:
    """Celery 薄适配层：桥接同步 Celery worker 与异步图执行。"""
    return asyncio.run(resume_orchestrator_async(result))


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    """演示桥接模块的结构（不实际连接 Redis）。"""
    print("celery_graph_bridge 模块结构:")
    print(f"  Celery app: {celery_app.main}")
    print(f"  dispatch_to_celery: 异步分发任务到 Celery")
    print(f"  resume_orchestrator: Celery 回调恢复图执行")
    print("  注意: 实际运行需要 Redis 和 Celery worker")


if __name__ == "__main__":
    _demo()
