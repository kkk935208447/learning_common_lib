"""Celery tasks for GlobalGraph start/resume orchestration."""

from __future__ import annotations

import asyncio
from typing import Any

try:
    from ..config import get_settings
    from ..domain.contracts import SubtaskResultEnvelope
    from ..ports.task_queue_port import TaskDispatchError
    from ..service_runtime import (
        build_global_graph_service_from_bundle,
        build_runtime_bundle,
        close_runtime_bundle,
    )
except ImportError:
    from 最小可执行demo.config import get_settings
    from 最小可执行demo.domain.contracts import SubtaskResultEnvelope
    from 最小可执行demo.ports.task_queue_port import TaskDispatchError
    from 最小可执行demo.service_runtime import (
        build_global_graph_service_from_bundle,
        build_runtime_bundle,
        close_runtime_bundle,
    )


async def _invoke_global_graph(
    *,
    runtime_bundle,
    task_id: int,
    entry_action: str | None = None,
    result_envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    graph_service = await build_global_graph_service_from_bundle(runtime_bundle, use_task_engine=True)
    return await graph_service.run(
        task_id,
        entry_action=entry_action,
        result_envelope=result_envelope,
    )


async def _run_with_task_lock(
    *,
    task_id: int,
    entry_action: str | None = None,
    result_envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime = build_runtime_bundle(use_task_engine=True)
    lock_key = f"deepsearch:orchestrate:{task_id}"
    token = runtime.redis_runtime.lock.try_lock(lock_key, get_settings().lock_ttl_seconds)
    if token is None:
        await close_runtime_bundle(runtime)
        return {"status": "locked"}
    try:
        return await _invoke_global_graph(
            runtime_bundle=runtime,
            task_id=task_id,
            entry_action=entry_action,
            result_envelope=result_envelope,
        )
    finally:
        runtime.redis_runtime.lock.release(lock_key, token)
        await close_runtime_bundle(runtime)


async def start_search_async(*, task_id: int, drain_eager: bool = True) -> dict[str, Any]:
    result = await _run_with_task_lock(task_id=task_id, entry_action=None)
    if result.get("status") != "locked":
        return result
    await asyncio.sleep(0.05)
    result = await _run_with_task_lock(task_id=task_id, entry_action=None)
    if result.get("status") != "locked" or get_settings().celery_eager:
        return result
    runtime = build_runtime_bundle(use_task_engine=True)
    try:
        runtime.task_queue.dispatch(
            task_name="deepsearch.start_search",
            payload={"task_id": task_id},
            queue_name="orchestrate_jobs",
            countdown=1,
        )
    except TaskDispatchError:
        pass
    await close_runtime_bundle(runtime)
    return result


async def resume_search_async(
    *,
    task_id: int,
    entry_action: str | None = None,
    result_envelope: dict[str, Any] | None = None,
    drain_eager: bool = True,
) -> dict[str, Any]:
    if result_envelope is not None and get_settings().celery_eager and drain_eager:
        runtime = build_runtime_bundle(use_task_engine=True)
        envelope = SubtaskResultEnvelope.model_validate(result_envelope)
        async with runtime.session_factory() as session:
            async with session.begin():
                await runtime.evidence_service.flush_staged_payload(session, envelope.execution_id)

    result = await _run_with_task_lock(
        task_id=task_id,
        entry_action=None,
        result_envelope=result_envelope,
    )
    if result.get("status") != "locked":
        return result
    await asyncio.sleep(0.05)
    result = await _run_with_task_lock(
        task_id=task_id,
        entry_action=None,
        result_envelope=result_envelope,
    )
    if result.get("status") != "locked" or get_settings().celery_eager:
        return result
    runtime = build_runtime_bundle(use_task_engine=True)
    try:
        runtime.task_queue.dispatch(
            task_name="deepsearch.resume_search",
            payload={
                "task_id": task_id,
                "entry_action": entry_action or "step_gate",
                "result_envelope": result_envelope,
            },
            queue_name="orchestrate_jobs",
            countdown=1,
        )
    except TaskDispatchError:
        pass
    await close_runtime_bundle(runtime)
    return result


def start_search_task(*, task_id: int) -> dict[str, Any]:
    return asyncio.run(start_search_async(task_id=task_id))


def resume_search_task(
    *,
    task_id: int,
    entry_action: str | None = None,
    result_envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        resume_search_async(
            task_id=task_id,
            entry_action=entry_action,
            result_envelope=result_envelope,
            drain_eager=True,
        )
    )
