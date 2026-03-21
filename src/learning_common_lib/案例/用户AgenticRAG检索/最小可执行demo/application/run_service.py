"""Plan activation, READY scheduling, dispatch bookkeeping, and result fencing."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ports.task_queue_port import TaskDispatchError
from .common import build_execution_id, json_safe, utcnow, value_of
from .progress_service import ProgressService

try:
    from ..infrastructure.models import SearchTask, Subtask, SubtaskRun, TaskPlan
except ImportError:
    from 最小可执行demo.infrastructure.models import SearchTask, Subtask, SubtaskRun, TaskPlan


TERMINAL_RUN_STATUSES = {"COMPLETED", "FAILED", "ESCALATED", "STALE_IGNORED"}


class RunService:
    def __init__(self, progress_service: ProgressService, task_queue) -> None:
        self.progress_service = progress_service
        self.task_queue = task_queue
        self.settings = get_settings()

    async def activate_plan(
        self,
        session: AsyncSession,
        *,
        task: SearchTask,
        plan_nodes: list,
        dag_fingerprint: str,
        replan_reason: str | None = None,
    ) -> int:
        previous_version = int(task.active_plan_version or 0)
        if previous_version > 0:
            old_plan = await session.scalar(
                select(TaskPlan).where(TaskPlan.task_id == task.id).where(TaskPlan.plan_version == previous_version)
            )
            if old_plan is not None:
                old_plan.status = "SUPERSEDED"

        new_version = previous_version + 1
        plan = TaskPlan(
            tenant_id=task.tenant_id,
            task_id=task.id,
            plan_version=new_version,
            parent_plan_version=previous_version or None,
            status="ACTIVE",
            dag_json={"nodes": [node.model_dump(mode="json") for node in plan_nodes]},
            dag_fingerprint=dag_fingerprint,
            replan_reason=replan_reason,
            reused_subtasks_json=[],
            created_at=utcnow(),
        )
        session.add(plan)
        for node in plan_nodes:
            session.add(
                Subtask(
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    plan_version=new_version,
                    subtask_code=node.subtask_code,
                    description=node.description,
                    task_type=node.task_type,
                    depends_on_json=[dep.model_dump(mode="json") for dep in node.depends_on],
                    route_hints_json=node.route_hints,
                    acceptance_criteria_json=node.acceptance_criteria,
                    budget_slice_json=node.budget_slice,
                    priority=node.priority,
                    status="PENDING",
                    iteration=0,
                    max_iterations=self.settings.max_subtask_iterations,
                    timeout_ms=self.settings.subtask_timeout_ms,
                    evidence_refs_json=[],
                    result_snapshot_json={},
                    row_version=0,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
        task.active_plan_version = new_version
        task.status = "EXECUTING"
        task.control_json = {
            **json_safe(task.control_json or {}),
            "waiting_reason": "NONE",
            "latest_escalation": None,
            "clarification_request": None,
        }
        await session.flush()
        await self.progress_service.append_event(
            session,
            tenant_id=task.tenant_id,
            task_id=task.id,
            event_type="plan_activated",
            payload_json={
                "status": "EXECUTING",
                "message": f"计划版本 {new_version} 已激活",
                "plan_version": new_version,
                "dag_fingerprint": dag_fingerprint,
            },
            plan_version=new_version,
        )
        return new_version

    async def ensure_ready_subtasks(
        self,
        session: AsyncSession,
        *,
        task_id: int,
        plan_version: int,
        for_update: bool = False,
    ) -> list[Subtask]:
        stmt = (
            select(Subtask)
            .where(Subtask.task_id == task_id)
            .where(Subtask.plan_version == plan_version)
            .order_by(Subtask.priority.asc(), Subtask.subtask_code.asc())
        )
        if for_update:
            stmt = stmt.with_for_update()
        subtasks = list((await session.scalars(stmt)).all())
        by_code = {item.subtask_code: item for item in subtasks}
        ready: list[Subtask] = []
        for item in subtasks:
            if value_of(item.status) not in {"PENDING", "READY"}:
                continue
            deps = item.depends_on_json or []
            missing_deps = [dep["code"] for dep in deps if dep.get("code") not in by_code]
            if missing_deps:
                item.status = "FAILED"
                item.last_error_code = "MISSING_DEPENDENCY"
                item.last_error_message = f"缺少依赖节点: {', '.join(missing_deps[:4])}"
                item.updated_at = utcnow()
                continue
            deps_met = all(value_of(by_code[dep["code"]].status) == "COMPLETED" for dep in deps)
            if deps_met:
                item.status = "READY"
                item.updated_at = utcnow()
                ready.append(item)
        await session.flush()
        return ready

    async def claim_ready_batch(
        self,
        session: AsyncSession,
        *,
        task: SearchTask,
        max_parallel: int | None = None,
    ) -> list[dict[str, Any]]:
        ready = await self.ensure_ready_subtasks(
            session,
            task_id=task.id,
            plan_version=task.active_plan_version,
            for_update=True,
        )
        claimed: list[dict[str, Any]] = []
        limit = max_parallel or self.settings.max_parallel_subtasks
        for subtask in ready[:limit]:
            attempt_stmt = (
                select(func.count(SubtaskRun.id))
                .where(SubtaskRun.task_id == task.id)
                .where(SubtaskRun.plan_version == task.active_plan_version)
                .where(SubtaskRun.subtask_code == subtask.subtask_code)
            )
            attempt_no = int((await session.scalar(attempt_stmt)) or 0) + 1
            execution_id = build_execution_id(task.id, task.active_plan_version, subtask.subtask_code, attempt_no)
            subtask.status = "RUNNING"
            subtask.current_execution_id = execution_id
            subtask.started_at = utcnow()
            subtask.updated_at = utcnow()
            subtask.iteration = int(subtask.iteration or 0) + 1
            run = SubtaskRun(
                tenant_id=task.tenant_id,
                task_id=task.id,
                plan_version=task.active_plan_version,
                subtask_code=subtask.subtask_code,
                execution_id=execution_id,
                attempt_no=attempt_no,
                status="CLAIMED",
                route_used_json=subtask.route_hints_json or [],
                usage_stats_json={},
                eval_json={},
                verify_json={},
                output_json={},
                escalation_json={},
                data_plane_ref_json={},
                data_plane_flush_status="PENDING",
                created_at=utcnow(),
            )
            session.add(run)
            await session.flush()
            await self.progress_service.append_event(
                session,
                tenant_id=task.tenant_id,
                task_id=task.id,
                event_type="subtask_claimed",
                payload_json={"status": "EXECUTING", "message": f"{subtask.subtask_code} 已认领"},
                plan_version=task.active_plan_version,
                subtask_code=subtask.subtask_code,
                execution_id=execution_id,
            )
            claimed.append(
                {
                    "execution_id": execution_id,
                    "subtask_code": subtask.subtask_code,
                    "attempt_no": attempt_no,
                }
            )

        await session.flush()
        return claimed

    async def mark_waiting_subtasks(
        self,
        session: AsyncSession,
        *,
        task: SearchTask,
        claimed_count: int,
    ) -> None:
        task.status = "WAITING_SUBTASKS"
        task.control_json = {**json_safe(task.control_json or {}), "waiting_reason": "SUBTASKS"}
        await self.progress_service.append_event(
            session,
            tenant_id=task.tenant_id,
            task_id=task.id,
            event_type="task_waiting_subtasks",
            payload_json={"status": "WAITING_SUBTASKS", "message": f"等待 {claimed_count} 个子任务执行"},
            plan_version=task.active_plan_version,
        )
        await session.flush()

    def dispatch_claimed_batch(self, *, claimed: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in claimed:
            execution_id = item["execution_id"]
            subtask_code = item["subtask_code"]
            try:
                self.task_queue.dispatch(
                    task_name="deepsearch.execute_subtask",
                    payload={"execution_id": execution_id},
                    queue_name="subtask_jobs",
                )
                results.append({"execution_id": execution_id, "subtask_code": subtask_code, "ok": True})
            except TaskDispatchError as exc:
                results.append(
                    {
                        "execution_id": execution_id,
                        "subtask_code": subtask_code,
                        "ok": False,
                        "error_code": f"dispatch_failed:{type(exc).__name__}",
                    }
                )
        return results

    async def persist_dispatch_results(
        self,
        session: AsyncSession,
        *,
        task: SearchTask,
        dispatch_results: list[dict[str, Any]],
    ) -> dict[str, int]:
        success_count = 0
        failed_count = 0
        for item in dispatch_results:
            execution_id = item["execution_id"]
            subtask_code = item["subtask_code"]
            if not item["ok"]:
                await self.mark_dispatch_failed(session, execution_id=execution_id, error_code=item["error_code"])
                failed_count += 1
                continue
            run = await session.scalar(select(SubtaskRun).where(SubtaskRun.execution_id == execution_id))
            if run is not None and value_of(run.status) == "CLAIMED":
                run.status = "DISPATCHED"
                success_count += 1
                await self.progress_service.append_event(
                    session,
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    event_type="subtask_dispatched",
                    payload_json={"status": "WAITING_SUBTASKS", "message": f"{subtask_code} 已分发"},
                    plan_version=task.active_plan_version,
                    subtask_code=subtask_code,
                    execution_id=execution_id,
                )

        if success_count > 0:
            await self.mark_waiting_subtasks(session, task=task, claimed_count=success_count)
        else:
            task.status = "EXECUTING"
            task.control_json = {**json_safe(task.control_json or {}), "waiting_reason": "NONE"}

        await session.flush()
        return {"success_count": success_count, "failed_count": failed_count}

    async def mark_dispatch_failed(self, session: AsyncSession, *, execution_id: str, error_code: str) -> None:
        run = await session.scalar(select(SubtaskRun).where(SubtaskRun.execution_id == execution_id))
        if run is None:
            return
        run.status = "FAILED"
        run.error_code = error_code
        subtask = await session.scalar(
            select(Subtask)
            .where(Subtask.task_id == run.task_id)
            .where(Subtask.plan_version == run.plan_version)
            .where(Subtask.subtask_code == run.subtask_code)
        )
        task = await session.scalar(select(SearchTask).where(SearchTask.id == run.task_id))
        if subtask is not None and subtask.current_execution_id == execution_id:
            subtask.status = "FAILED"
            subtask.last_error_code = "DISPATCH_FAILED"
            subtask.last_error_message = error_code[:1024]
            subtask.current_execution_id = None
            subtask.updated_at = utcnow()
        if task is not None:
            task.last_error_code = "DISPATCH_FAILED"
            task.last_error_message = error_code[:1024]
            await self.progress_service.append_event(
                session,
                tenant_id=task.tenant_id,
                task_id=task.id,
                event_type="subtask_dispatch_failed",
                payload_json={
                    "status": "EXECUTING",
                    "message": f"{run.subtask_code} 分发失败",
                    "error_code": error_code,
                },
                plan_version=run.plan_version,
                subtask_code=run.subtask_code,
                execution_id=execution_id,
            )
        await session.flush()

    async def apply_subtask_result(self, session: AsyncSession, envelope) -> bool:
        run = await session.scalar(
            select(SubtaskRun).where(SubtaskRun.execution_id == envelope.execution_id).with_for_update()
        )
        task = await session.scalar(select(SearchTask).where(SearchTask.id == envelope.task_id).with_for_update())
        subtask = await session.scalar(
            select(Subtask)
            .where(Subtask.task_id == envelope.task_id)
            .where(Subtask.plan_version == envelope.plan_version)
            .where(Subtask.subtask_code == envelope.subtask_code)
            .with_for_update()
        )
        if run is None or task is None or subtask is None:
            return False
        if value_of(run.status) in TERMINAL_RUN_STATUSES:
            return False

        if int(task.active_plan_version or 0) != envelope.plan_version or subtask.current_execution_id != envelope.execution_id:
            run.status = "STALE_IGNORED"
            run.finished_at = utcnow()
            await self.progress_service.append_event(
                session,
                tenant_id=task.tenant_id,
                task_id=task.id,
                event_type="subtask_stale_ignored",
                payload_json={
                    "status": value_of(task.status),
                    "message": f"{envelope.subtask_code} 旧执行结果已忽略",
                },
                plan_version=envelope.plan_version,
                subtask_code=envelope.subtask_code,
                execution_id=envelope.execution_id,
            )
            await session.flush()
            return False

        run.usage_stats_json = envelope.usage_stats
        run.eval_json = envelope.eval_summary
        run.verify_json = envelope.verify_summary
        run.output_json = {
            "output_text": envelope.output_text,
            "evidence_card_refs": envelope.evidence_card_refs,
        }
        run.data_plane_ref_json = {
            "l2_working_memory_ref": {
                "namespace": "subtask_memory",
                "key": envelope.execution_id,
            },
            "l3_evidence_pool_ref": {
                "namespace": "evidence_pool",
                "key": f"{task.request_id}:{envelope.plan_version}",
            },
        }
        run.error_code = envelope.error_code
        run.finished_at = utcnow()

        if envelope.status == "COMPLETED":
            run.status = "COMPLETED"
            subtask.status = "COMPLETED"
            subtask.final_score = envelope.eval_summary.get("total_score")
            subtask.key_findings = envelope.output_text
            subtask.evidence_refs_json = envelope.evidence_card_refs
            subtask.result_snapshot_json = {
                "output_text": envelope.output_text,
                "verify_summary": envelope.verify_summary,
                "eval_summary": envelope.eval_summary,
            }
            subtask.completed_at = utcnow()
            event_type = "subtask_completed"
            message = f"{envelope.subtask_code} 已完成"
        elif envelope.status == "ESCALATED":
            run.status = "ESCALATED"
            run.escalation_json = envelope.escalation_report.model_dump(mode="json") if envelope.escalation_report else {}
            subtask.status = "FAILED"
            subtask.last_error_code = "ESCALATED"
            subtask.last_error_message = envelope.escalation_report.message[:1024] if envelope.escalation_report else "子任务升级"
            task.control_json = {
                **json_safe(task.control_json or {}),
                "latest_escalation": envelope.escalation_report.model_dump(mode="json") if envelope.escalation_report else None,
            }
            event_type = "subtask_escalated"
            message = f"{envelope.subtask_code} 已升级"
        else:
            run.status = "FAILED"
            subtask.status = "FAILED"
            subtask.last_error_code = envelope.error_code or "SUBTASK_FAILED"
            subtask.last_error_message = (envelope.output_text or envelope.error_code or "子任务失败")[:1024]
            event_type = "subtask_failed"
            message = f"{envelope.subtask_code} 已失败"

        subtask.updated_at = utcnow()
        task.status = "EXECUTING"
        task.control_json = {
            **json_safe(task.control_json or {}),
            "waiting_reason": "NONE",
            "latest_result_ref": envelope.result_ref,
        }
        await self.progress_service.append_event(
            session,
            tenant_id=task.tenant_id,
            task_id=task.id,
            event_type=event_type,
            payload_json={"status": "EXECUTING", "message": message},
            plan_version=envelope.plan_version,
            subtask_code=envelope.subtask_code,
            execution_id=envelope.execution_id,
        )
        await session.flush()
        return True

    async def decide_next_action(self, session: AsyncSession, *, task: SearchTask) -> str:
        plan_version = int(task.active_plan_version or 0)
        subtasks = list(
            (
                await session.scalars(
                    select(Subtask)
                    .where(Subtask.task_id == task.id)
                    .where(Subtask.plan_version == plan_version)
                    .order_by(Subtask.priority.asc(), Subtask.subtask_code.asc())
                )
            ).all()
        )
        if not subtasks:
            return "fallback"

        await self.ensure_ready_subtasks(session, task_id=task.id, plan_version=plan_version)
        states = [value_of(item.status) for item in subtasks]
        control_json = json_safe(task.control_json or {})
        latest_escalation = control_json.get("latest_escalation")
        if "READY" in states:
            return "schedule"
        if "RUNNING" in states:
            task.status = "WAITING_SUBTASKS"
            task.control_json = {**control_json, "waiting_reason": "SUBTASKS"}
            await session.flush()
            return "output"
        if all(state in {"COMPLETED", "SKIPPED"} for state in states):
            return "finalize"
        if latest_escalation and latest_escalation.get("suggested_global_action") == "clarify" and int(task.postexec_clarification_used or 0) < 1:
            return "clarify"
        if any(state == "FAILED" for state in states) and int(task.replan_count or 0) < self.settings.max_replan_count:
            return "replan"
        if any(state == "FAILED" for state in states):
            return "finalize"
        return "fallback"
