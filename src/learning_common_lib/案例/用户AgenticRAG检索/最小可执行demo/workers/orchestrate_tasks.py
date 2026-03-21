"""Celery tasks for GlobalGraph start/resume orchestration."""

from __future__ import annotations

import asyncio
from typing import Any

try:
    from sqlalchemy import select
    from ..config import get_settings
    from ..domain.contracts import SubtaskResultEnvelope
    from ..infrastructure.models import SearchTask, SubtaskRun
    from ..service_runtime import build_global_graph_service, build_runtime_bundle
except ImportError:
    from sqlalchemy import select
    from 最小可执行demo.config import get_settings
    from 最小可执行demo.domain.contracts import SubtaskResultEnvelope
    from 最小可执行demo.infrastructure.models import SearchTask, SubtaskRun
    from 最小可执行demo.service_runtime import build_global_graph_service, build_runtime_bundle


async def _process_claimed_runs(*, task_id: int) -> None:
    try:
        from ..service_runtime import build_subtask_graph_service
    except ImportError:
        from 最小可执行demo.service_runtime import build_subtask_graph_service

    runtime = build_runtime_bundle(use_task_engine=True)
    service = build_subtask_graph_service(use_task_engine=True)
    async with runtime.session_factory() as session:
        task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
        if task is None:
            return
        plan_version = int(task.active_plan_version or 0)
        runs = list(
            (
                await session.scalars(
                    select(SubtaskRun)
                    .where(SubtaskRun.task_id == task_id)
                    .where(SubtaskRun.plan_version == plan_version)
                    .where(SubtaskRun.status.in_(("CLAIMED", "DISPATCHED")))
                    .order_by(SubtaskRun.id.asc())
                )
            ).all()
        )
    for run in runs:
        envelope = await service.execute(execution_id=run.execution_id)
        if envelope is None:
            continue
        async with runtime.session_factory() as session:
            async with session.begin():
                await runtime.run_service.apply_subtask_result(session, envelope)
        async with runtime.session_factory() as session:
            async with session.begin():
                await runtime.evidence_service.flush_staged_payload(session, run.execution_id)


async def _drive_control_plane(
    *,
    task_id: int,
    entry_action: str | None = None,
    eager: bool,
    max_rounds: int = 50,
) -> dict[str, Any]:
    runtime = build_runtime_bundle(use_task_engine=True)
    graph_service = await build_global_graph_service(use_task_engine=True)
    action = entry_action
    lock_key = f"deepsearch:orchestrate:{task_id}"
    token = runtime.redis_runtime.lock.try_lock(lock_key, get_settings().lock_ttl_seconds)
    if token is None:
        return {"status": "locked"}

    try:
        for _ in range(max_rounds):
            async with runtime.session_factory() as session:
                task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
            if task is None:
                return {"status": "missing"}
            status = getattr(task.status, "value", task.status)
            if status in {"COMPLETED", "FAILED", "DEGRADED", "WAITING_CLARIFICATION"}:
                return {"status": status}

            if action is None:
                action = "intake" if int(task.active_plan_version or 0) == 0 else "step_gate"

            state = graph_service._build_initial_state(task, entry_action=action)

            if action == "intake":
                state.update(await graph_service.intake_node(state))
                action = "planner"
                continue

            if action == "planner":
                state.update(await graph_service.planner_node(state))
                next_action = state.get("next_action")
                if next_action == "clarify":
                    state.update(await graph_service.clarify_node(state))
                    return {"status": "WAITING_CLARIFICATION"}
                if next_action == "fallback":
                    state.update(await graph_service.fallback_node(state))
                    return {"status": "fallback"}
                action = "scheduler"
                continue

            if action == "scheduler":
                state.update(await graph_service.scheduler_node(state))
                action = "executor" if int(state.get("ready_count", 0)) > 0 else "step_gate"
                continue

            if action == "executor":
                state.update(await graph_service.executor_node(state))
                next_action = state.get("next_action", "output")
                if eager:
                    if next_action == "step_gate":
                        action = "step_gate"
                        continue
                    if next_action == "fallback":
                        state.update(await graph_service.fallback_node(state))
                        return {"status": "fallback"}
                    await _process_claimed_runs(task_id=task_id)
                    action = "step_gate"
                    continue
                if next_action == "step_gate":
                    action = "step_gate"
                    continue
                if next_action == "fallback":
                    state.update(await graph_service.fallback_node(state))
                    return {"status": "fallback"}
                return {"status": "waiting_subtasks"}

            if action == "step_gate":
                state.update(await graph_service.step_gate_node(state))
                next_action = state.get("next_action")
                if next_action == "schedule":
                    action = "scheduler"
                    continue
                if next_action == "replan":
                    action = "replan"
                    continue
                if next_action == "clarify":
                    state.update(await graph_service.clarify_node(state))
                    return {"status": "WAITING_CLARIFICATION"}
                if next_action == "finalize":
                    state.update(await graph_service.finalize_node(state))
                    return {"status": "finalized"}
                if next_action == "fallback":
                    state.update(await graph_service.fallback_node(state))
                    return {"status": "fallback"}
                return {"status": status, "action": next_action}

            if action == "replan":
                state.update(await graph_service.replan_node(state))
                next_action = state.get("next_action")
                if next_action == "fallback":
                    state.update(await graph_service.fallback_node(state))
                    return {"status": "fallback"}
                action = "planner"
                continue

            return {"status": status, "action": action}

        return {"status": "max_rounds_exceeded"}
    finally:
        runtime.redis_runtime.lock.release(lock_key, token)


async def start_search_async(*, task_id: int, drain_eager: bool = True) -> dict[str, Any]:
    result = await _drive_control_plane(
        task_id=task_id,
        entry_action="intake",
        eager=get_settings().celery_eager and drain_eager,
    )
    if result.get("status") != "locked":
        return result
    await asyncio.sleep(0.05)
    return await _drive_control_plane(
        task_id=task_id,
        entry_action="intake",
        eager=get_settings().celery_eager and drain_eager,
    )


async def resume_search_async(
    *,
    task_id: int,
    entry_action: str | None = None,
    result_envelope: dict[str, Any] | None = None,
    drain_eager: bool = True,
) -> dict[str, Any]:
    if result_envelope is not None:
        runtime = build_runtime_bundle(use_task_engine=True)
        envelope = SubtaskResultEnvelope.model_validate(result_envelope)
        async with runtime.session_factory() as session:
            async with session.begin():
                await runtime.run_service.apply_subtask_result(session, envelope)
        if get_settings().celery_eager and drain_eager:
            async with runtime.session_factory() as session:
                async with session.begin():
                    await runtime.evidence_service.flush_staged_payload(session, envelope.execution_id)
    result = await _drive_control_plane(
        task_id=task_id,
        entry_action=entry_action or "step_gate",
        eager=get_settings().celery_eager and drain_eager,
    )
    if result.get("status") != "locked":
        return result
    await asyncio.sleep(0.05)
    return await _drive_control_plane(
        task_id=task_id,
        entry_action=entry_action or "step_gate",
        eager=get_settings().celery_eager and drain_eager,
    )


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
