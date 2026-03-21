"""Celery tasks for SubtaskGraph execution."""

from __future__ import annotations

import asyncio

try:
    from ..config import get_settings
    from ..domain.enums import QueueName, TaskName
    from ..ports.task_queue_port import TaskDispatchError
    from ..service_runtime import (
        build_runtime_bundle,
        build_subtask_graph_service_from_bundle,
        close_runtime_bundle,
    )
    from .orchestrate_tasks import resume_search_async
    from .persist_tasks import flush_data_plane_async
except ImportError:
    from 最小可执行demo.config import get_settings
    from 最小可执行demo.domain.enums import QueueName, TaskName
    from 最小可执行demo.ports.task_queue_port import TaskDispatchError
    from 最小可执行demo.service_runtime import (
        build_runtime_bundle,
        build_subtask_graph_service_from_bundle,
        close_runtime_bundle,
    )
    from 最小可执行demo.workers.orchestrate_tasks import resume_search_async
    from 最小可执行demo.workers.persist_tasks import flush_data_plane_async


async def execute_subtask_async(*, execution_id: str, **_: object) -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    try:
        service = build_subtask_graph_service_from_bundle(runtime)
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
            persist_payload = {
                "execution_id": execution_id,
                "resume_payload": {
                    "task_id": envelope.task_id,
                    "entry_action": "step_gate",
                    "result_envelope": envelope.model_dump(mode="json"),
                },
            }
            try:
                runtime.task_queue.dispatch(
                    task_name=TaskName.FLUSH_DATA_PLANE.value,
                    payload=persist_payload,
                    queue_name=QueueName.PERSIST.value,
                )
            except TaskDispatchError:
                await flush_data_plane_async(**persist_payload)
        return envelope.model_dump(mode="json")
    finally:
        await close_runtime_bundle(runtime)


def execute_subtask_task(*, execution_id: str, **kwargs: object) -> dict:
    return asyncio.run(execute_subtask_async(execution_id=execution_id, **kwargs))
