"""Celery tasks for data-plane persistence."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

try:
    from ..service_runtime import build_runtime_bundle, close_runtime_bundle
except ImportError:
    from 最小可执行demo.service_runtime import build_runtime_bundle, close_runtime_bundle


logger = logging.getLogger(__name__)


async def flush_data_plane_async(
    *,
    execution_id: str,
    resume_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime = build_runtime_bundle(use_task_engine=True)
    try:
        async with runtime.session_factory() as session:
            async with session.begin():
                flush_result = await runtime.evidence_service.flush_staged_payload(session, execution_id)

        inserted = int(flush_result.get("inserted", 0) or 0)
        request_id = flush_result.get("request_id")
        task_id = flush_result.get("task_id")
        plan_version = flush_result.get("plan_version")
        if flush_result.get("orphaned") or flush_result.get("stale"):
            await runtime.evidence_service.delete_staged_payload(execution_id)
        elif request_id is not None and task_id is not None and plan_version is not None:
            try:
                await runtime.evidence_service.sync_evidence_pool_from_db(
                    runtime.session_factory,
                    task_id=int(task_id),
                    request_id=str(request_id),
                    plan_version=int(plan_version),
                )
                await runtime.evidence_service.delete_staged_payload(execution_id)
            except Exception:
                logger.exception("failed to sync evidence_pool after execution_id=%s", execution_id)

        return {
            "inserted": inserted,
            "stale_ignored": bool(flush_result.get("stale")),
            "resume_dispatched": False,
            "resume_payload_ignored": resume_payload is not None,
        }
    finally:
        await close_runtime_bundle(runtime)


def flush_data_plane_task(
    *,
    execution_id: str,
    resume_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return asyncio.run(flush_data_plane_async(execution_id=execution_id, resume_payload=resume_payload))
