"""Celery tasks for SubtaskGraph execution."""

from __future__ import annotations

import asyncio

try:
    from ..config import get_settings
    from ..domain.enums import QueueName, TaskName
    from ..service_runtime import build_runtime_bundle, build_subtask_graph_service
    from .orchestrate_tasks import resume_search_async
    from .persist_tasks import flush_data_plane_async
except ImportError:
    from 最小可执行demo.config import get_settings
    from 最小可执行demo.domain.enums import QueueName, TaskName
    from 最小可执行demo.service_runtime import build_runtime_bundle, build_subtask_graph_service
    from 最小可执行demo.workers.orchestrate_tasks import resume_search_async
    from 最小可执行demo.workers.persist_tasks import flush_data_plane_async


async def execute_subtask_async(*, execution_id: str, **_: object) -> dict:
    service = build_subtask_graph_service(use_task_engine=True)
    envelope = await service.execute(execution_id=execution_id)
    if envelope is None:
        return {"status": "ignored"}

    settings = get_settings()
    if settings.celery_eager:
        await flush_data_plane_async(execution_id=execution_id)
        await resume_search_async(
            task_id=envelope.task_id,
            entry_action="step_gate",
            result_envelope=envelope.model_dump(mode="json"),
            drain_eager=False,
        )
    else:
        runtime = build_runtime_bundle(use_task_engine=True)
        runtime.task_queue.dispatch(
            task_name=TaskName.FLUSH_DATA_PLANE.value,
            payload={"execution_id": execution_id},
            queue_name=QueueName.PERSIST.value,
        )
        runtime.task_queue.dispatch(
            task_name=TaskName.RESUME_SEARCH.value,
            payload={
                "task_id": envelope.task_id,
                "entry_action": "step_gate",
                "result_envelope": envelope.model_dump(mode="json"),
            },
            queue_name=QueueName.ORCHESTRATE.value,
        )
    return envelope.model_dump(mode="json")


def execute_subtask_task(*, execution_id: str, **kwargs: object) -> dict:
    return asyncio.run(execute_subtask_async(execution_id=execution_id, **kwargs))
