"""Celery tasks for GlobalGraph start/resume orchestration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

try:
    from ..infrastructure.runtime_bundle import (
        build_global_graph_service_from_bundle,
        build_runtime_bundle,
        close_runtime_bundle,
    )
    from ..infrastructure.settings import get_settings
    from ..ports.task_queue_port import TaskDispatchError
except ImportError:
    from 最小可执行demo.infrastructure.runtime_bundle import (
        build_global_graph_service_from_bundle,
        build_runtime_bundle,
        close_runtime_bundle,
    )
    from 最小可执行demo.infrastructure.settings import get_settings
    from 最小可执行demo.ports.task_queue_port import TaskDispatchError


logger = logging.getLogger(__name__)


async def _invoke_global_graph(
    *,
    runtime_bundle,
    task_id: int,
    entry_action: str | None = None,
    result_envelope: dict[str, Any] | None = None,
    prefer_checkpoint: bool = False,
) -> dict[str, Any]:
    graph_service = await build_global_graph_service_from_bundle(runtime_bundle, use_task_engine=True)
    logger.info(
        "invoke global graph task_id=%s entry_action=%s prefer_checkpoint=%s has_result=%s",
        task_id,
        entry_action,
        prefer_checkpoint,
        result_envelope is not None,
    )
    return await graph_service.run(
        task_id,
        entry_action=entry_action,
        result_envelope=result_envelope,
        prefer_checkpoint=prefer_checkpoint,
    )


async def _run_with_task_lock(
    *,
    task_id: int,
    entry_action: str | None = None,
    result_envelope: dict[str, Any] | None = None,
    prefer_checkpoint: bool = False,
) -> dict[str, Any]:
    runtime = build_runtime_bundle(use_task_engine=True)
    lock_key = f"deepsearch:orchestrate:{task_id}"
    token = runtime.redis_runtime.lock.try_lock(lock_key, get_settings().lock_ttl_seconds)
    if token is None:
        logger.info("orchestrate lock busy task_id=%s", task_id)
        await close_runtime_bundle(runtime)
        return {"status": "locked"}
    try:
        return await _invoke_global_graph(
            runtime_bundle=runtime,
            task_id=task_id,
            entry_action=entry_action,
            result_envelope=result_envelope,
            prefer_checkpoint=prefer_checkpoint,
        )
    finally:
        runtime.redis_runtime.lock.release(lock_key, token)
        await close_runtime_bundle(runtime)


async def start_search_async(
    *,
    task_id: int,
    drain_eager: bool = True,
    prefer_checkpoint: bool = False,
) -> dict[str, Any]:
    logger.info("start search task_id=%s prefer_checkpoint=%s", task_id, prefer_checkpoint)
    result = await _run_with_task_lock(
        task_id=task_id,
        entry_action=None,
        prefer_checkpoint=prefer_checkpoint,
    )
    if result.get("status") != "locked":
        return result
    await asyncio.sleep(0.05)
    result = await _run_with_task_lock(
        task_id=task_id,
        entry_action=None,
        prefer_checkpoint=prefer_checkpoint,
    )
    if result.get("status") != "locked" or get_settings().celery_eager:
        return result
    runtime = build_runtime_bundle(use_task_engine=True)
    try:
        runtime.task_queue.dispatch(
            task_name="deepsearch.start_search",
            payload={"task_id": task_id, "prefer_checkpoint": prefer_checkpoint},
            queue_name="orchestrate_jobs",
            countdown=1,
        )
    except TaskDispatchError:
        pass
    finally:
        await close_runtime_bundle(runtime)
    return result


async def resume_search_async(
    *,
    task_id: int,
    entry_action: str | None = None,
    result_envelope: dict[str, Any] | None = None,
    drain_eager: bool = True,
    prefer_checkpoint: bool = False,
) -> dict[str, Any]:
    logger.info(
        "resume search task_id=%s entry_action=%s prefer_checkpoint=%s has_result=%s",
        task_id,
        entry_action,
        prefer_checkpoint,
        result_envelope is not None,
    )
    result = await _run_with_task_lock(
        task_id=task_id,
        entry_action=entry_action,
        result_envelope=result_envelope,
        prefer_checkpoint=prefer_checkpoint,
    )
    if result.get("status") != "locked":
        return result
    await asyncio.sleep(0.05)
    result = await _run_with_task_lock(
        task_id=task_id,
        entry_action=entry_action,
        result_envelope=result_envelope,
        prefer_checkpoint=prefer_checkpoint,
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
                "prefer_checkpoint": prefer_checkpoint,
            },
            queue_name="orchestrate_jobs",
            countdown=1,
        )
    except TaskDispatchError:
        pass
    finally:
        await close_runtime_bundle(runtime)
    return result


def start_search_task(*, task_id: int, prefer_checkpoint: bool = False) -> dict[str, Any]:
    return asyncio.run(start_search_async(task_id=task_id, prefer_checkpoint=prefer_checkpoint))


def resume_search_task(
    *,
    task_id: int,
    entry_action: str | None = None,
    result_envelope: dict[str, Any] | None = None,
    prefer_checkpoint: bool = False,
) -> dict[str, Any]:
    return asyncio.run(
        resume_search_async(
            task_id=task_id,
            entry_action=entry_action,
            result_envelope=result_envelope,
            drain_eager=True,
            prefer_checkpoint=prefer_checkpoint,
        )
    )
