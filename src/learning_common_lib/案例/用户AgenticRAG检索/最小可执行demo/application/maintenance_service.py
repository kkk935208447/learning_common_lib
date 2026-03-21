"""Background maintenance routines for stuck runs and clarify defaults."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.enums import QueueName, TaskName
from .common import json_safe, utcnow
from .progress_service import ProgressService
from .session_service import SessionService

try:
    from ..infrastructure.models import SearchTask, Subtask, SubtaskRun
except ImportError:
    from 最小可执行demo.infrastructure.models import SearchTask, Subtask, SubtaskRun


class MaintenanceService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        task_queue,
        progress_service: ProgressService,
        session_service: SessionService,
        redis_runtime,
    ) -> None:
        self.session_factory = session_factory
        self.task_queue = task_queue
        self.progress_service = progress_service
        self.session_service = session_service
        self.redis_runtime = redis_runtime

    async def _dispatch_or_resume(self, payload: dict[str, object]) -> None:
        try:
            self.task_queue.dispatch(
                task_name=TaskName.RESUME_SEARCH.value,
                payload=payload,
                queue_name=QueueName.ORCHESTRATE.value,
            )
        except Exception:
            try:
                from ..workers.orchestrate_tasks import resume_search_async
            except ImportError:
                from 最小可执行demo.workers.orchestrate_tasks import resume_search_async

            await resume_search_async(**payload)

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
                            select(SearchTask).where(SearchTask.status == "WAITING_CLARIFICATION")
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
                    deadline = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).replace(tzinfo=None)
                    if deadline > utcnow():
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
                        "clarification_request": None,
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

    async def rebuild_runtime_cache(self) -> dict[str, str]:
        await self.redis_runtime.save_json(
            "maintenance",
            "last_rebuild",
            {"ts": utcnow().isoformat()},
            ttl_seconds=600,
        )
        return {"status": "ok"}
