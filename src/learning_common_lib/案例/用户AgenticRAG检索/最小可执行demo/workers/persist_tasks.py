"""Celery tasks for data-plane persistence."""

from __future__ import annotations

import asyncio
from typing import Any

try:
    from ..domain.enums import QueueName, TaskName
    from ..ports.task_queue_port import TaskDispatchError
    from ..service_runtime import build_runtime_bundle, close_runtime_bundle
except ImportError:
    from 最小可执行demo.domain.enums import QueueName, TaskName
    from 最小可执行demo.ports.task_queue_port import TaskDispatchError
    from 最小可执行demo.service_runtime import build_runtime_bundle, close_runtime_bundle


async def flush_data_plane_async(
    *,
    execution_id: str,
    resume_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime = build_runtime_bundle(use_task_engine=True)
    try:
        async with runtime.session_factory() as session:
            async with session.begin():
                inserted = await runtime.evidence_service.flush_staged_payload(session, execution_id)

        dispatched_resume = False
        if resume_payload is not None:
            try:
                runtime.task_queue.dispatch(
                    task_name=TaskName.RESUME_SEARCH.value,
                    payload=resume_payload,
                    queue_name=QueueName.ORCHESTRATE.value,
                )
                dispatched_resume = True
            except TaskDispatchError:
                try:
                    from .orchestrate_tasks import resume_search_async
                except ImportError:
                    from 最小可执行demo.workers.orchestrate_tasks import resume_search_async

                await resume_search_async(**resume_payload)
        return {"inserted": inserted, "resume_dispatched": dispatched_resume}
    finally:
        await close_runtime_bundle(runtime)


def flush_data_plane_task(
    *,
    execution_id: str,
    resume_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return asyncio.run(flush_data_plane_async(execution_id=execution_id, resume_payload=resume_payload))
