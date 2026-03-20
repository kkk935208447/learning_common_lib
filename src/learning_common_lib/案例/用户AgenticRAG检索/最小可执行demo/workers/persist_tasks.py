"""Celery tasks for data-plane persistence."""

from __future__ import annotations

import asyncio

try:
    from ..service_runtime import build_runtime_bundle
except ImportError:
    from 最小可执行demo.service_runtime import build_runtime_bundle


async def flush_data_plane_async(*, execution_id: str) -> dict[str, int]:
    runtime = build_runtime_bundle(use_task_engine=True)
    async with runtime.session_factory() as session:
        async with session.begin():
            inserted = await runtime.evidence_service.flush_staged_payload(session, execution_id)
    return {"inserted": inserted}


def flush_data_plane_task(*, execution_id: str) -> dict[str, int]:
    return asyncio.run(flush_data_plane_async(execution_id=execution_id))
