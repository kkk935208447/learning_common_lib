"""Celery tasks for maintenance routines."""

from __future__ import annotations

import asyncio

try:
    from ..service_runtime import build_maintenance_service
except ImportError:
    from 最小可执行demo.service_runtime import build_maintenance_service


async def reap_stuck_runs_async() -> dict[str, int]:
    service = build_maintenance_service(use_task_engine=True)
    reaped = await service.reap_stuck_runs()
    return {"reaped": reaped}


async def apply_clarify_defaults_async() -> dict[str, int]:
    service = build_maintenance_service(use_task_engine=True)
    applied = await service.apply_clarification_defaults()
    return {"applied": applied}


async def rebuild_runtime_cache_async() -> dict[str, str]:
    service = build_maintenance_service(use_task_engine=True)
    return await service.rebuild_runtime_cache()


def reap_stuck_runs_task() -> dict[str, int]:
    return asyncio.run(reap_stuck_runs_async())


def apply_clarify_defaults_task() -> dict[str, int]:
    return asyncio.run(apply_clarify_defaults_async())


def rebuild_runtime_cache_task() -> dict[str, str]:
    return asyncio.run(rebuild_runtime_cache_async())
