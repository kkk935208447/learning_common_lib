"""Celery tasks for maintenance routines."""

from __future__ import annotations

import asyncio

try:
    from ..service_runtime import build_maintenance_service_from_bundle, build_runtime_bundle, close_runtime_bundle
except ImportError:
    from 最小可执行demo.service_runtime import build_maintenance_service_from_bundle, build_runtime_bundle, close_runtime_bundle


async def reap_stuck_runs_async() -> dict[str, int]:
    runtime = build_runtime_bundle(use_task_engine=True)
    try:
        service = build_maintenance_service_from_bundle(runtime)
        reaped = await service.reap_stuck_runs()
        return {"reaped": reaped}
    finally:
        await close_runtime_bundle(runtime)


async def apply_clarify_defaults_async() -> dict[str, int]:
    runtime = build_runtime_bundle(use_task_engine=True)
    try:
        service = build_maintenance_service_from_bundle(runtime)
        applied = await service.apply_clarification_defaults()
        return {"applied": applied}
    finally:
        await close_runtime_bundle(runtime)


async def rebuild_runtime_cache_async() -> dict[str, str]:
    runtime = build_runtime_bundle(use_task_engine=True)
    try:
        service = build_maintenance_service_from_bundle(runtime)
        return await service.rebuild_runtime_cache()
    finally:
        await close_runtime_bundle(runtime)


async def recover_orchestration_gaps_async() -> dict[str, int]:
    runtime = build_runtime_bundle(use_task_engine=True)
    try:
        service = build_maintenance_service_from_bundle(runtime)
        return await service.recover_orchestration_gaps()
    finally:
        await close_runtime_bundle(runtime)


def reap_stuck_runs_task() -> dict[str, int]:
    return asyncio.run(reap_stuck_runs_async())


def apply_clarify_defaults_task() -> dict[str, int]:
    return asyncio.run(apply_clarify_defaults_async())


def rebuild_runtime_cache_task() -> dict[str, str]:
    return asyncio.run(rebuild_runtime_cache_async())


def recover_orchestration_gaps_task() -> dict[str, int]:
    return asyncio.run(recover_orchestration_gaps_async())
