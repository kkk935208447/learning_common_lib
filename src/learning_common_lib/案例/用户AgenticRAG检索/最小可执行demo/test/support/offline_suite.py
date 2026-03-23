"""Offline test helpers that use the service layer while Celery worker/beat run externally."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from sqlalchemy import select

try:
    from ...domain.contracts import SearchSubmitRequest
    from ...application.common import utcnow
    from ...infrastructure.runtime_bundle import (
        build_maintenance_service,
        build_runtime_bundle,
        build_search_command_service,
    )
    from ...infrastructure.models import SearchTask, SessionTurn, SubtaskRun, TaskEvent
    from .production_stack_suite import (
        test_checkpoint_does_not_mutate_redis_url_env,
        test_checkpoint_resume_recovery,
        test_dag_fingerprint_distinguishes_semantics,
        test_fallback_returns_partial_results,
        test_final_answer_filters_invalid_citations,
        test_maintenance_recovery_resumes_planning_and_finalizing,
        test_maintenance_recovery_resumes_ready_tasks,
        test_maintenance_recovery_resumes_terminal_plan,
        test_replan_creates_distinct_plan_and_reuses_completed_subtasks,
        test_redis_memory_layers,
        test_stale_result_does_not_advance_new_plan,
    )
except ImportError:
    from 最小可执行demo.domain.contracts import SearchSubmitRequest
    from 最小可执行demo.application.common import utcnow
    from 最小可执行demo.infrastructure.runtime_bundle import (
        build_maintenance_service,
        build_runtime_bundle,
        build_search_command_service,
    )
    from 最小可执行demo.infrastructure.models import SearchTask, SessionTurn, SubtaskRun, TaskEvent
    from 最小可执行demo.test.support.production_stack_suite import (
        test_checkpoint_does_not_mutate_redis_url_env,
        test_checkpoint_resume_recovery,
        test_dag_fingerprint_distinguishes_semantics,
        test_fallback_returns_partial_results,
        test_final_answer_filters_invalid_citations,
        test_maintenance_recovery_resumes_planning_and_finalizing,
        test_maintenance_recovery_resumes_ready_tasks,
        test_maintenance_recovery_resumes_terminal_plan,
        test_replan_creates_distinct_plan_and_reuses_completed_subtasks,
        test_redis_memory_layers,
        test_stale_result_does_not_advance_new_plan,
    )


async def poll_offline_snapshot(request_id: str, *, timeout_s: int = 60) -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    for _ in range(timeout_s):
        async with runtime.session_factory() as session:
            snapshot = await runtime.progress_service.build_snapshot(session, request_id)
        if snapshot.status in {"COMPLETED", "DEGRADED", "FAILED", "WAITING_CLARIFICATION"}:
            return snapshot.model_dump(mode="json")
        await asyncio.sleep(1)
    raise RuntimeError(f"offline snapshot polling timed out for {request_id}")


async def submit_offline_query(*, session_id: str, query: str) -> str:
    service = build_search_command_service(use_task_engine=True)
    accepted = await service.submit_search(
        SearchSubmitRequest(
            session_id=session_id,
            query=query,
            kb_code="default",
            scope_json=None,
        )
    )
    return accepted.request_id


async def test_offline_happy_path() -> dict:
    request_id = await submit_offline_query(
        session_id="sess_test_offline_happy_path",
        query="请帮我整理公司近 90 天差旅报销规则的变化",
    )
    snapshot = await poll_offline_snapshot(request_id)
    if snapshot["status"] != "COMPLETED":
        raise AssertionError(f"offline happy path expected COMPLETED, got {snapshot['status']}")
    return {"request_id": request_id, "final_status": snapshot["status"]}


async def test_offline_preplan_clarify() -> dict:
    request_id = await submit_offline_query(
        session_id="sess_test_offline_preplan_clarify",
        query="请帮我整理差旅报销规则的变化",
    )
    snapshot = await poll_offline_snapshot(request_id)
    if snapshot["status"] != "WAITING_CLARIFICATION":
        raise AssertionError(f"offline preplan clarify expected WAITING_CLARIFICATION, got {snapshot['status']}")
    clarification = snapshot["clarification_request"]
    service = build_search_command_service(use_task_engine=True)
    await service.submit_clarification(request_id, clarification["default_option_id"])
    final_snapshot = await poll_offline_snapshot(request_id)
    if final_snapshot["status"] != "COMPLETED":
        raise AssertionError(f"offline preplan clarify expected COMPLETED, got {final_snapshot['status']}")
    return {"request_id": request_id, "final_status": final_snapshot["status"]}


async def test_offline_step_gate_clarify() -> dict:
    request_id = await submit_offline_query(
        session_id="sess_test_offline_step_gate_clarify",
        query="请按你认为更合适的口径整理公司近 90 天差旅报销规则的变化",
    )
    snapshot = await poll_offline_snapshot(request_id)
    if snapshot["status"] != "WAITING_CLARIFICATION":
        raise AssertionError(f"offline step gate clarify expected WAITING_CLARIFICATION, got {snapshot['status']}")
    clarification = snapshot["clarification_request"]
    if clarification["clarification_source"] != "STEP_GATE":
        raise AssertionError(f"expected STEP_GATE clarification, got {clarification}")
    service = build_search_command_service(use_task_engine=True)
    await service.submit_clarification(request_id, "opt_policy")
    final_snapshot = await poll_offline_snapshot(request_id)
    if final_snapshot["status"] != "COMPLETED":
        raise AssertionError(f"offline step gate clarify expected COMPLETED, got {final_snapshot['status']}")
    if not str(final_snapshot.get("final_answer") or "").startswith("回答口径：制度解释优先"):
        raise AssertionError(f"step gate clarify should respect user choice, got {final_snapshot.get('final_answer')}")
    return {"request_id": request_id, "final_status": final_snapshot["status"]}


async def test_offline_subtask_retry() -> dict:
    request_id = await submit_offline_query(
        session_id="sess_test_offline_subtask_retry",
        query="请帮我整理公司近 90 天差旅报销规则的变化",
    )
    snapshot = await poll_offline_snapshot(request_id)
    if snapshot["status"] != "COMPLETED":
        raise AssertionError(f"offline subtask retry expected COMPLETED, got {snapshot['status']}")
    return {"request_id": request_id, "final_status": snapshot["status"]}


async def test_offline_replan_flow() -> dict:
    request_id = await submit_offline_query(
        session_id="sess_test_offline_replan_flow",
        query="请帮我整理公司近 90 天差旅报销规则的变化",
    )
    snapshot = await poll_offline_snapshot(request_id, timeout_s=90)
    if snapshot["status"] != "COMPLETED":
        raise AssertionError(f"offline replan flow expected COMPLETED after real replan, got {snapshot['status']}")
    runtime = build_runtime_bundle(use_task_engine=True)
    async with runtime.session_factory() as session:
        task = await session.scalar(select(SearchTask).where(SearchTask.request_id == request_id))
        if task is None:
            raise AssertionError("offline replan flow task missing")
        events = list(
            (
                await session.scalars(
                    select(TaskEvent)
                    .where(TaskEvent.task_id == task.id)
                    .order_by(TaskEvent.id.asc())
                )
            ).all()
        )
    if int(task.replan_count or 0) < 1:
        raise AssertionError(f"offline replan flow expected replan_count >= 1, got {task.replan_count}")
    event_names = [event.event_type for event in events]
    if "task_replanned" not in event_names:
        raise AssertionError(f"offline replan flow expected task_replanned event, got {event_names}")
    return {
        "request_id": request_id,
        "final_status": snapshot["status"],
        "replan_count": int(task.replan_count or 0),
    }


async def test_replan_reuse_flow() -> dict:
    return await test_replan_creates_distinct_plan_and_reuses_completed_subtasks()


async def test_dispatch_gap_recovery() -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    maintenance = build_maintenance_service(use_task_engine=True)
    async with runtime.session_factory() as session:
        async with session.begin():
            await runtime.session_service.ensure_session(
                session,
                session_id="sess_test_dispatch_gap_recovery",
                tenant_id="demo-tenant",
                user_id="demo-user",
                initial_query="请帮我整理公司近 90 天差旅报销规则的变化",
            )
            task = SearchTask(
                request_id=f"req_test_dispatch_gap_recovery_{int(utcnow().timestamp() * 1000)}",
                session_id="sess_test_dispatch_gap_recovery",
                tenant_id="demo-tenant",
                user_id="demo-user",
                kb_code="default",
                scope_json=None,
                original_query="请帮我整理公司近 90 天差旅报销规则的变化",
                resolved_query="请帮我整理公司近 90 天差旅报销规则的变化",
                task_profile_json={},
                status="PENDING",
                active_plan_version=0,
                budget_json={},
                control_json={"waiting_reason": "NONE"},
                replan_count=0,
                clarification_count=0,
                preplan_clarification_used=0,
                postexec_clarification_used=0,
                row_version=0,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(task)
            await session.flush()
            outcome = runtime.plan_service.create_plan(
                original_query=task.original_query,
                resolved_query=task.resolved_query,
                allow_clarify=False,
            )
            await runtime.run_service.activate_plan(
                session,
                task=task,
                plan_nodes=outcome.plan_nodes,
                dag_fingerprint=outcome.dag_fingerprint,
            )
            claimed = await runtime.run_service.claim_ready_batch(session, task=task, max_parallel=1)
            if not claimed:
                raise AssertionError("dispatch gap test expected a claimed run")
            run = await session.scalar(select(SubtaskRun).where(SubtaskRun.execution_id == claimed[0]["execution_id"]).with_for_update())
            if run is None:
                raise AssertionError("dispatch gap test run missing")
            run.created_at = utcnow() - timedelta(minutes=5)
            request_id = task.request_id
    recovered = await maintenance.recover_dispatch_gaps(stall_seconds=0)
    if recovered < 1:
        raise AssertionError(f"dispatch gap recovery expected recovered >= 1, got {recovered}")
    snapshot = await poll_offline_snapshot(request_id)
    if snapshot["status"] != "COMPLETED":
        raise AssertionError(f"dispatch gap recovery expected COMPLETED, got {snapshot['status']}")
    return {"request_id": request_id, "recovered": recovered, "final_status": snapshot["status"]}


async def test_runtime_cache_rebuild() -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    maintenance = build_maintenance_service(use_task_engine=True)
    request_id = await submit_offline_query(
        session_id="sess_test_runtime_cache_rebuild",
        query="请按你认为更合适的口径整理公司近 90 天差旅报销规则的变化",
    )
    snapshot = await poll_offline_snapshot(request_id)
    if snapshot["status"] != "WAITING_CLARIFICATION":
        raise AssertionError(
            f"runtime cache rebuild expected WAITING_CLARIFICATION before rebuild, got {snapshot['status']}"
        )
    async with runtime.session_factory() as session:
        task = await session.scalar(select(SearchTask).where(SearchTask.request_id == request_id))
        if task is None:
            raise AssertionError("runtime cache rebuild task missing")
        cache_key = f"{task.request_id}:{task.active_plan_version}"
        task_id = task.id
        latest_turn = await session.scalar(
            select(SessionTurn)
            .where(SessionTurn.task_id == task.id)
            .where(SessionTurn.turn_type == "CLARIFY_REQUEST")
            .order_by(SessionTurn.id.desc())
            .limit(1)
        )
        if latest_turn is None:
            raise AssertionError("runtime cache rebuild expected a clarify request turn")
    await runtime.redis_runtime.delete_json("snapshot_cache", request_id)
    await runtime.redis_runtime.delete_json_list("event_cache", request_id)
    await runtime.redis_runtime.delete_json("evidence_pool", cache_key)
    await runtime.redis_runtime.delete_json("global_state", str(task_id))
    summary = await maintenance.rebuild_runtime_cache()
    cached_snapshot = await runtime.progress_service.load_cached_snapshot(request_id)
    cached_events = await runtime.progress_service.load_cached_events_after(request_id, 0)
    evidence_pool = await runtime.redis_runtime.load_json("evidence_pool", cache_key)
    global_state = await runtime.redis_runtime.load_json("global_state", str(task_id))
    if cached_snapshot is None or not cached_events or not evidence_pool or not global_state:
        raise AssertionError(
            f"runtime cache rebuild expected snapshot/events/evidence/global_state to be restored, got {summary}"
        )
    return {
        "request_id": request_id,
        "status": summary["status"],
        "primed_event_caches": int(summary["primed_event_caches"]),
    }


async def test_checkpoint_resume_recovery_flow() -> dict:
    return await test_checkpoint_resume_recovery()
