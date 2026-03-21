"""Background maintenance routines for stuck runs and clarify defaults."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import get_settings
from ..domain.enums import QueueName, TaskName
from .common import json_safe, parse_utc_datetime, utcnow, value_of
from .progress_service import ProgressService
from .session_service import SessionService

try:
    from ..infrastructure.models import SearchTask, Subtask, SubtaskRun, TaskEvent
    from ..ports.task_queue_port import TaskDispatchError
except ImportError:
    from 最小可执行demo.infrastructure.models import SearchTask, Subtask, SubtaskRun, TaskEvent
    from 最小可执行demo.ports.task_queue_port import TaskDispatchError


class MaintenanceService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        task_queue,
        progress_service: ProgressService,
        session_service: SessionService,
        redis_runtime,
        evidence_service,
    ) -> None:
        self.session_factory = session_factory
        self.task_queue = task_queue
        self.progress_service = progress_service
        self.session_service = session_service
        self.redis_runtime = redis_runtime
        self.evidence_service = evidence_service

    async def _dispatch_or_resume(self, payload: dict[str, object]) -> None:
        try:
            self.task_queue.dispatch(
                task_name=TaskName.RESUME_SEARCH.value,
                payload=payload,
                queue_name=QueueName.ORCHESTRATE.value,
            )
        except TaskDispatchError:
            try:
                from ..workers.orchestrate_tasks import resume_search_async
            except ImportError:
                from 最小可执行demo.workers.orchestrate_tasks import resume_search_async

            await resume_search_async(**payload)

    async def _dispatch_or_start(self, payload: dict[str, object]) -> None:
        try:
            self.task_queue.dispatch(
                task_name=TaskName.START_SEARCH.value,
                payload=payload,
                queue_name=QueueName.ORCHESTRATE.value,
            )
        except TaskDispatchError:
            try:
                from ..workers.orchestrate_tasks import start_search_async
            except ImportError:
                from 最小可执行demo.workers.orchestrate_tasks import start_search_async

            await start_search_async(**payload)

    async def reap_stuck_runs(self, timeout_seconds: int = 90) -> int:
        cutoff = utcnow() - timedelta(seconds=timeout_seconds)
        reaped = 0
        resume_payloads: list[dict[str, object]] = []
        async with self.session_factory() as session:
            async with session.begin():
                runs = list(
                    (
                        await session.scalars(
                            select(SubtaskRun).where(SubtaskRun.status.in_(("CLAIMED", "DISPATCHED", "RUNNING")))
                        )
                    ).all()
                )
                for run in runs:
                    compare_at = run.started_at or run.created_at
                    if compare_at is None or compare_at >= cutoff:
                        continue
                    task = await session.scalar(select(SearchTask).where(SearchTask.id == run.task_id))
                    subtask = await session.scalar(
                        select(Subtask)
                        .where(Subtask.task_id == run.task_id)
                        .where(Subtask.plan_version == run.plan_version)
                        .where(Subtask.subtask_code == run.subtask_code)
                    )
                    if task is None or subtask is None:
                        continue
                    run.status = "FAILED"
                    run.error_code = "STUCK_RUN_TIMEOUT"
                    run.finished_at = utcnow()
                    if subtask.current_execution_id == run.execution_id:
                        subtask.status = "FAILED"
                        subtask.last_error_code = "STUCK_RUN_TIMEOUT"
                        subtask.last_error_message = "执行超时，等待全局控制面恢复"
                    await self.progress_service.append_event(
                        session,
                        tenant_id=task.tenant_id,
                        task_id=task.id,
                        event_type="subtask_run_reaped",
                        payload_json={
                            "status": "EXECUTING",
                            "message": f"{run.subtask_code} 执行超时，已收割",
                        },
                        plan_version=run.plan_version,
                        subtask_code=run.subtask_code,
                        execution_id=run.execution_id,
                    )
                    resume_payloads.append({"task_id": task.id, "entry_action": "step_gate"})
                    reaped += 1
        for payload in resume_payloads:
            await self._dispatch_or_resume(payload)
        return reaped

    async def apply_clarification_defaults(self) -> int:
        applied = 0
        resume_payloads: list[dict[str, object]] = []
        async with self.session_factory() as session:
            async with session.begin():
                tasks = list(
                    (
                        await session.scalars(
                            select(SearchTask)
                            .where(SearchTask.status == "WAITING_CLARIFICATION")
                            .with_for_update()
                        )
                    ).all()
                )
                for task in tasks:
                    control_json = json_safe(task.control_json or {})
                    clarification_request = control_json.get("clarification_request")
                    if not clarification_request:
                        continue
                    expires_at = clarification_request.get("expires_at")
                    if not expires_at:
                        continue
                    deadline = parse_utc_datetime(expires_at)
                    if deadline is None or deadline > utcnow():
                        continue
                    if control_json.get("clarification_reply_selected"):
                        continue
                    selected_option_id = clarification_request["default_option_id"]
                    clarification_source = control_json.get("clarification_source") or "PREPLAN"
                    await self.session_service.record_clarification_reply(
                        session,
                        session_id=task.session_id,
                        task_id=task.id,
                        selected_option_id=selected_option_id,
                        answer_origin="DEFAULT_APPLIED",
                    )
                    task.status = "EXECUTING"
                    task.control_json = {
                        **control_json,
                        "clarification_reply_selected": selected_option_id,
                        "clarification_source": clarification_source,
                        "waiting_reason": "NONE",
                    }
                    await self.progress_service.append_event(
                        session,
                        tenant_id=task.tenant_id,
                        task_id=task.id,
                        event_type="clarification_default_applied",
                        payload_json={
                            "status": "EXECUTING",
                            "message": f"澄清超时，已应用默认选项 {selected_option_id}",
                        },
                        plan_version=task.active_plan_version,
                    )
                    resume_payloads.append(
                        {
                            "task_id": task.id,
                            "entry_action": "planner" if clarification_source == "PREPLAN" else "step_gate",
                        }
                    )
                    applied += 1
        for payload in resume_payloads:
            await self._dispatch_or_resume(payload)
        return applied

    async def recover_orchestration_gaps(self, stall_seconds: int | None = None) -> dict[str, int]:
        cutoff = utcnow() - timedelta(seconds=stall_seconds or max(15, get_settings().maintenance_scan_seconds * 2))
        redispatched = await self.recover_dispatch_gaps(stall_seconds=stall_seconds)
        start_payloads: list[dict[str, object]] = []
        resume_payloads: list[dict[str, object]] = []
        recovered_start = 0
        recovered_resume = 0

        async with self.session_factory() as session:
            async with session.begin():
                tasks = list(
                    (
                        await session.scalars(
                            select(SearchTask)
                            .where(
                                SearchTask.status.in_(
                                    ("PENDING", "PLANNING", "EXECUTING", "WAITING_SUBTASKS", "FINALIZING")
                                )
                            )
                            .where(SearchTask.updated_at < cutoff)
                            .with_for_update()
                        )
                    ).all()
                )
                for task in tasks:
                    control_json = json_safe(task.control_json or {})
                    status = value_of(task.status)
                    if status == "PENDING" and int(task.active_plan_version or 0) == 0:
                        start_payloads.append({"task_id": task.id})
                        recovered_start += 1
                    elif status == "PLANNING":
                        resume_payloads.append({"task_id": task.id, "entry_action": "planner"})
                        recovered_resume += 1
                    elif status == "FINALIZING" and int(task.active_plan_version or 0) > 0:
                        resume_payloads.append({"task_id": task.id, "entry_action": "finalize"})
                        recovered_resume += 1
                    elif control_json.get("clarification_reply_selected"):
                        clarification_source = control_json.get("clarification_source") or "PREPLAN"
                        resume_payloads.append(
                            {
                                "task_id": task.id,
                                "entry_action": "planner" if clarification_source == "PREPLAN" else "step_gate",
                            }
                        )
                        recovered_resume += 1
                    elif status in {"EXECUTING", "WAITING_SUBTASKS"} and int(task.active_plan_version or 0) > 0:
                        subtasks = list(
                            (
                                await session.scalars(
                                    select(Subtask)
                                    .where(Subtask.task_id == task.id)
                                    .where(Subtask.plan_version == task.active_plan_version)
                                )
                            ).all()
                        )
                        states = {value_of(item.status) for item in subtasks}
                        if subtasks and states.issubset({"COMPLETED", "FAILED", "SKIPPED"}):
                            resume_payloads.append({"task_id": task.id, "entry_action": "step_gate"})
                            recovered_resume += 1

                for payload in start_payloads:
                    task_id = int(payload["task_id"])
                    task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
                    if task is None:
                        continue
                    await self.progress_service.append_event(
                        session,
                        tenant_id=task.tenant_id,
                        task_id=task.id,
                        event_type="task_recovery_scheduled",
                        payload_json={"status": value_of(task.status), "message": "维护任务补发初始编排"},
                        plan_version=task.active_plan_version,
                    )
                for payload in resume_payloads:
                    task_id = int(payload["task_id"])
                    task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
                    if task is None:
                        continue
                    await self.progress_service.append_event(
                        session,
                        tenant_id=task.tenant_id,
                        task_id=task.id,
                        event_type="task_recovery_scheduled",
                        payload_json={"status": value_of(task.status), "message": "维护任务补发恢复编排"},
                        plan_version=task.active_plan_version,
                    )

        for payload in start_payloads:
            await self._dispatch_or_start(payload)
        for payload in resume_payloads:
            await self._dispatch_or_resume(payload)
        return {"started": recovered_start, "resumed": recovered_resume, "redispatched": redispatched}

    async def recover_dispatch_gaps(self, stall_seconds: int | None = None) -> int:
        cutoff = utcnow() - timedelta(seconds=stall_seconds or max(15, get_settings().maintenance_scan_seconds * 2))
        redeliveries: list[dict[str, object]] = []
        recovered = 0
        async with self.session_factory() as session:
            async with session.begin():
                runs = list(
                    (
                        await session.scalars(
                            select(SubtaskRun)
                            .where(SubtaskRun.status.in_(("CLAIMED", "DISPATCHED")))
                            .where(SubtaskRun.created_at < cutoff)
                            .with_for_update()
                        )
                    ).all()
                )
                for run in runs:
                    task = await session.scalar(select(SearchTask).where(SearchTask.id == run.task_id))
                    subtask = await session.scalar(
                        select(Subtask)
                        .where(Subtask.task_id == run.task_id)
                        .where(Subtask.plan_version == run.plan_version)
                        .where(Subtask.subtask_code == run.subtask_code)
                    )
                    if task is None or subtask is None:
                        continue
                    if int(task.active_plan_version or 0) != run.plan_version or subtask.current_execution_id != run.execution_id:
                        continue
                    events = list(
                        (
                            await session.scalars(
                                select(TaskEvent)
                                .where(TaskEvent.execution_id == run.execution_id)
                                .order_by(TaskEvent.id.asc())
                            )
                        ).all()
                    )
                    event_types = {event.event_type for event in events}
                    if "subtask_started" in event_types:
                        continue
                    if value_of(run.status) == "CLAIMED" or "subtask_dispatched" not in event_types:
                        run.status = "DISPATCHED"
                        await self.progress_service.append_event(
                            session,
                            tenant_id=task.tenant_id,
                            task_id=task.id,
                            event_type="subtask_dispatched",
                            payload_json={
                                "status": value_of(task.status),
                                "message": f"{run.subtask_code} 由维护任务补发",
                            },
                            plan_version=run.plan_version,
                            subtask_code=run.subtask_code,
                            execution_id=run.execution_id,
                        )
                    redeliveries.append({"execution_id": run.execution_id})
                    recovered += 1
        for payload in redeliveries:
            try:
                self.task_queue.dispatch(
                    task_name=TaskName.EXECUTE_SUBTASK.value,
                    payload=payload,
                    queue_name=QueueName.SUBTASK.value,
                )
            except TaskDispatchError:
                try:
                    from ..workers.subtask_tasks import execute_subtask_async
                except ImportError:
                    from 最小可执行demo.workers.subtask_tasks import execute_subtask_async

                await execute_subtask_async(**payload)
        return recovered

    async def rebuild_runtime_cache(self) -> dict[str, int | str]:
        active_tasks: list[SearchTask] = []
        async with self.session_factory() as session:
            active_tasks = list(
                (
                    await session.scalars(
                        select(SearchTask).where(
                            SearchTask.status.in_(
                                (
                                    "PENDING",
                                    "PLANNING",
                                    "EXECUTING",
                                    "WAITING_SUBTASKS",
                                    "WAITING_CLARIFICATION",
                                    "FINALIZING",
                                )
                            )
                        )
                    )
                ).all()
            )

        synced = 0
        primed_events = 0
        for task in active_tasks:
            plan_version = int(task.active_plan_version or 0)
            if plan_version <= 0:
                continue
            await self.evidence_service.sync_evidence_pool_from_db(
                self.session_factory,
                task_id=task.id,
                request_id=task.request_id,
                plan_version=plan_version,
            )
            cache_summary = await self.progress_service.prime_task_cache(
                self.session_factory,
                request_id=task.request_id,
            )
            runtime_cache = getattr(self.progress_service, "runtime_cache", None)
            if runtime_cache is not None:
                await runtime_cache.store_global_state(
                    task.id,
                    {
                        "task_id": task.id,
                        "request_id": task.request_id,
                        "active_plan_version": plan_version,
                        "status": value_of(task.status),
                        "waiting_reason": json_safe(task.control_json or {}).get("waiting_reason", "NONE"),
                    },
                )
            primed_events += int(cache_summary.get("events", 0))
            synced += 1

        await self.redis_runtime.save_json(
            "maintenance",
            "last_rebuild",
            {"ts": utcnow().isoformat()},
            ttl_seconds=600,
        )
        return {
            "status": "ok",
            "synced_evidence_pools": synced,
            "primed_event_caches": primed_events,
        }
