"""GlobalGraph orchestration for the first deep search demo."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import get_settings
from ..domain.clarify_rules import apply_clarification_to_query
from ..domain.contracts import ClarificationOption, ClarificationRequest
from ..domain.state import GlobalState
from .common import json_safe, value_of

try:
    from ..infrastructure.models import SearchTask, Subtask
except ImportError:
    from 最小可执行demo.infrastructure.models import SearchTask, Subtask


class GlobalGraphService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        plan_service,
        run_service,
        evidence_service,
        progress_service,
        session_service,
        checkpointer=None,
    ) -> None:
        self.session_factory = session_factory
        self.plan_service = plan_service
        self.run_service = run_service
        self.evidence_service = evidence_service
        self.progress_service = progress_service
        self.session_service = session_service
        self.graph = self._build_graph(checkpointer=checkpointer)

    def _build_graph(self, checkpointer=None):
        graph = StateGraph(GlobalState)
        graph.add_node("dispatch", self.dispatch_node)
        graph.add_node("intake", self.intake_node)
        graph.add_node("planner", self.planner_node)
        graph.add_node("clarify", self.clarify_node)
        graph.add_node("scheduler", self.scheduler_node)
        graph.add_node("executor", self.executor_node)
        graph.add_node("step_gate", self.step_gate_node)
        graph.add_node("replan", self.replan_node)
        graph.add_node("finalize", self.finalize_node)
        graph.add_node("fallback", self.fallback_node)
        graph.add_node("output", self.output_node)

        graph.add_edge(START, "dispatch")
        graph.add_conditional_edges("dispatch", self.route_entry)
        graph.add_edge("intake", "planner")
        graph.add_conditional_edges("planner", self.route_by_action)
        graph.add_conditional_edges("clarify", self.route_by_action)
        graph.add_conditional_edges("scheduler", self.route_after_scheduler)
        graph.add_conditional_edges("executor", self.route_by_action)
        graph.add_conditional_edges("step_gate", self.route_by_action)
        graph.add_edge("replan", "planner")
        graph.add_conditional_edges("finalize", self.route_by_action)
        graph.add_conditional_edges("fallback", self.route_by_action)
        graph.add_edge("output", END)
        return graph.compile(checkpointer=checkpointer)

    async def run(self, task_id: int, *, entry_action: str | None = None) -> dict[str, Any]:
        async with self.session_factory() as session:
            task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
            if task is None:
                raise ValueError(f"task_id={task_id} 不存在")
            initial_state = self._build_initial_state(task, entry_action=entry_action)
        config = {"configurable": {"thread_id": f"deepsearch-task-{task_id}"}}
        return await self.graph.ainvoke(initial_state, config=config)

    def _build_initial_state(self, task: SearchTask, *, entry_action: str | None = None) -> GlobalState:
        control_json = json_safe(task.control_json or {})
        if entry_action is None:
            if int(task.active_plan_version or 0) == 0:
                entry_action = "intake"
            elif control_json.get("clarification_reply_selected"):
                source = control_json.get("clarification_source") or "PREPLAN"
                entry_action = "planner" if source == "PREPLAN" else "step_gate"
            elif value_of(task.status) in {"WAITING_CLARIFICATION"}:
                entry_action = "output"
            elif value_of(task.status) in {"PENDING", "PLANNING"}:
                entry_action = "intake"
            elif value_of(task.status) in {"EXECUTING", "WAITING_SUBTASKS"}:
                entry_action = "step_gate"
            elif value_of(task.status) in {"FINALIZING"}:
                entry_action = "finalize"
            else:
                entry_action = "output"
        return GlobalState(
            entry_action=entry_action,
            task_id=task.id,
            request_id=task.request_id,
            session_id=task.session_id,
            tenant_id=task.tenant_id,
            user_id=task.user_id,
            original_query=task.original_query,
            resolved_query=task.resolved_query or task.original_query,
            active_plan_version=int(task.active_plan_version or 0),
            global_iteration=int(task.replan_count or 0),
            budget=json_safe(task.budget_json or {}),
            replan_count=int(task.replan_count or 0),
            clarification_count=int(task.clarification_count or 0),
            waiting_reason=control_json.get("waiting_reason", "NONE"),
            clarification_source=control_json.get("clarification_source"),
            clarification_ref=control_json.get("clarification_request"),
            historical_fingerprints=control_json.get("historical_fingerprints", []),
            latest_result_ref=control_json.get("latest_result_ref"),
            pending_resume_execution_id=control_json.get("pending_resume_execution_id"),
            next_action="output",
            final_answer=task.final_answer,
            error=task.last_error_code,
        )

    async def dispatch_node(self, state: GlobalState) -> dict[str, Any]:
        return state

    async def intake_node(self, state: GlobalState) -> dict[str, Any]:
        async with self.session_factory() as session:
            task = await session.scalar(select(SearchTask).where(SearchTask.id == state["task_id"]))
            if task is None:
                return {"next_action": "fallback", "error": "TASK_NOT_FOUND"}
            task.status = "PLANNING"
            task.budget_json = {"llm_tokens": 4000, "retrieval_calls": 12, "max_parallel_subtasks": 3}
            task.control_json = {**json_safe(task.control_json or {}), "waiting_reason": "NONE"}
            await self.progress_service.append_event(
                session,
                tenant_id=task.tenant_id,
                task_id=task.id,
                event_type="task_planning_started",
                payload_json={"status": "PLANNING", "message": "开始任务画像与规划"},
            )
            await session.commit()
            budget = json_safe(task.budget_json)
        return {"next_action": "planner", "budget": budget}

    async def planner_node(self, state: GlobalState) -> dict[str, Any]:
        async with self.session_factory() as session:
            task = await session.scalar(select(SearchTask).where(SearchTask.id == state["task_id"]))
            if task is None:
                return {"next_action": "fallback", "error": "TASK_NOT_FOUND"}

            control_json = json_safe(task.control_json or {})
            resolved_query = apply_clarification_to_query(
                task.resolved_query or task.original_query,
                control_json.get("clarification_request"),
                control_json.get("clarification_reply_selected"),
            )
            allow_clarify = int(task.preplan_clarification_used or 0) < 1 and not control_json.get("clarification_reply_selected")
            outcome = self.plan_service.create_plan(
                original_query=task.original_query,
                resolved_query=resolved_query,
                allow_clarify=allow_clarify,
            )
            task.resolved_query = outcome.resolved_query
            if outcome.clarification_request is not None:
                control_json["pending_generated_clarification"] = outcome.clarification_request.model_dump(mode="json")
                control_json["clarification_source"] = "PREPLAN"
                task.control_json = control_json
                await session.commit()
                return {
                    "next_action": "clarify",
                    "clarification_ref": outcome.clarification_request.model_dump(mode="json"),
                    "clarification_source": "PREPLAN",
                }

            control_json.pop("clarification_reply_selected", None)
            control_json.pop("pending_generated_clarification", None)
            control_json.setdefault("historical_fingerprints", []).append(outcome.dag_fingerprint)
            task.control_json = control_json
            plan_version = await self.run_service.activate_plan(
                session,
                task=task,
                plan_nodes=outcome.plan_nodes,
                dag_fingerprint=outcome.dag_fingerprint,
                replan_reason="replan" if int(task.replan_count or 0) > 0 else None,
            )
            await session.commit()
        return {"next_action": "schedule", "active_plan_version": plan_version}

    async def clarify_node(self, state: GlobalState) -> dict[str, Any]:
        async with self.session_factory() as session:
            task = await session.scalar(select(SearchTask).where(SearchTask.id == state["task_id"]))
            if task is None:
                return {"next_action": "fallback"}
            control_json = json_safe(task.control_json or {})
            raw = state.get("clarification_ref") or control_json.get("pending_generated_clarification")
            if raw is None:
                raw = ClarificationRequest(
                    question="请选择你希望优先关注的范围",
                    options=[
                        ClarificationOption(id="opt_all", label="全部活动知识"),
                        ClarificationOption(id="opt_core", label="核心制度范围"),
                    ],
                    default_option_id="opt_all",
                    clarification_source="STEP_GATE",
                    expires_at=datetime.utcnow() + timedelta(minutes=10),
                    reason_code="postexec_gap",
                ).model_dump(mode="json")
            clarification = ClarificationRequest.model_validate(raw)
            task.status = "WAITING_CLARIFICATION"
            task.clarification_count = int(task.clarification_count or 0) + 1
            if clarification.clarification_source == "PREPLAN":
                task.preplan_clarification_used = int(task.preplan_clarification_used or 0) + 1
            else:
                task.postexec_clarification_used = int(task.postexec_clarification_used or 0) + 1
            task.control_json = {
                **control_json,
                "waiting_reason": "CLARIFICATION",
                "clarification_request": clarification.model_dump(mode="json"),
                "clarification_source": clarification.clarification_source,
                "pending_generated_clarification": None,
            }
            await self.session_service.record_clarification_request(
                session,
                session_id=task.session_id,
                task_id=task.id,
                clarification=clarification,
            )
            await self.progress_service.append_event(
                session,
                tenant_id=task.tenant_id,
                task_id=task.id,
                event_type="clarification_requested",
                payload_json={
                    "status": "WAITING_CLARIFICATION",
                    "message": clarification.question,
                    "clarification_request": clarification.model_dump(mode="json"),
                },
                plan_version=task.active_plan_version,
            )
            await self.progress_service.append_event(
                session,
                tenant_id=task.tenant_id,
                task_id=task.id,
                event_type="task_waiting_clarification",
                payload_json={"status": "WAITING_CLARIFICATION", "message": "等待用户补充关键信息"},
                plan_version=task.active_plan_version,
            )
            await session.commit()
        return {"next_action": "output"}

    async def scheduler_node(self, state: GlobalState) -> dict[str, Any]:
        async with self.session_factory() as session:
            task = await session.scalar(select(SearchTask).where(SearchTask.id == state["task_id"]))
            if task is None:
                return {"next_action": "fallback", "ready_count": 0}
            ready = await self.run_service.ensure_ready_subtasks(session, task_id=task.id, plan_version=task.active_plan_version)
            await session.commit()
            return {"ready_count": len(ready)}

    async def executor_node(self, state: GlobalState) -> dict[str, Any]:
        claimed: list[dict[str, Any]] = []
        task_id = state["task_id"]
        async with self.session_factory() as session:
            task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
            if task is None:
                return {"next_action": "fallback"}
            claimed = await self.run_service.claim_ready_batch(session, task=task, max_parallel=3)
            await session.commit()
            tenant_id = task.tenant_id
            active_plan_version = task.active_plan_version
            request_id = task.request_id

        if not claimed:
            return {"next_action": "step_gate"}

        if get_settings().celery_eager:
            return {"next_action": "output"}

        dispatch_results = self.run_service.dispatch_claimed_batch(
            task=SimpleNamespace(
                id=task_id,
                tenant_id=tenant_id,
                request_id=request_id,
                active_plan_version=active_plan_version,
            ),
            claimed=claimed,
        )
        async with self.session_factory() as session:
            task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
            if task is not None:
                await self.run_service.persist_dispatch_results(
                    session,
                    task=task,
                    dispatch_results=dispatch_results,
                )
                await session.commit()
        return {"next_action": "output"}

    async def step_gate_node(self, state: GlobalState) -> dict[str, Any]:
        async with self.session_factory() as session:
            task = await session.scalar(select(SearchTask).where(SearchTask.id == state["task_id"]))
            if task is None:
                return {"next_action": "fallback"}
            next_action = await self.run_service.decide_next_action(session, task=task)
            control_json = json_safe(task.control_json or {})
            if next_action == "clarify":
                control_json["pending_generated_clarification"] = ClarificationRequest(
                    question="请选择你希望优先保留的回答口径",
                    options=[
                        ClarificationOption(id="opt_policy", label="制度解释优先"),
                        ClarificationOption(id="opt_change", label="变更摘要优先"),
                    ],
                    default_option_id="opt_change",
                    clarification_source="STEP_GATE",
                    expires_at=datetime.utcnow() + timedelta(minutes=10),
                    reason_code="postexec_gap",
                ).model_dump(mode="json")
                task.control_json = control_json
            await session.commit()
        return {"next_action": next_action}

    async def replan_node(self, state: GlobalState) -> dict[str, Any]:
        async with self.session_factory() as session:
            task = await session.scalar(select(SearchTask).where(SearchTask.id == state["task_id"]))
            if task is None:
                return {"next_action": "fallback"}
            task.replan_count = int(task.replan_count or 0) + 1
            task.status = "PLANNING"
            task.control_json = {**json_safe(task.control_json or {}), "latest_escalation": None, "waiting_reason": "NONE"}
            await self.progress_service.append_event(
                session,
                tenant_id=task.tenant_id,
                task_id=task.id,
                event_type="task_replanned",
                payload_json={"status": "PLANNING", "message": f"开始第 {task.replan_count} 次重规划"},
                plan_version=task.active_plan_version,
            )
            await session.commit()
        return {"next_action": "planner"}

    async def finalize_node(self, state: GlobalState) -> dict[str, Any]:
        async with self.session_factory() as session:
            task = await session.scalar(select(SearchTask).where(SearchTask.id == state["task_id"]))
            if task is None:
                return {"next_action": "fallback"}
            subtasks = list(
                (
                    await session.scalars(
                        select(Subtask)
                        .where(Subtask.task_id == task.id)
                        .where(Subtask.plan_version == task.active_plan_version)
                    )
                ).all()
            )
            for item in subtasks:
                if value_of(item.status) not in {"COMPLETED", "FAILED", "SKIPPED"}:
                    item.status = "FAILED"
                    item.last_error_code = "FINALIZE_UNFINISHED"
                    item.last_error_message = "任务在最终收口阶段结束，节点未继续执行。"
            assembled = await self.evidence_service.assemble_final_answer(session, task_id=task.id, plan_version=task.active_plan_version)
            task.final_answer = assembled["answer"]
            task.status = "DEGRADED" if assembled["coverage_summary"]["uncovered"] else "COMPLETED"
            task.control_json = {
                **json_safe(task.control_json or {}),
                "waiting_reason": "NONE",
                "final_citations": assembled["citations"],
                "coverage_summary": assembled["coverage_summary"],
                "final_input": assembled["final_input"],
            }
            await self.session_service.append_answer_turn(
                session,
                session_id=task.session_id,
                task_id=task.id,
                answer=assembled["answer"],
                citations=assembled["citations"],
                coverage_summary=assembled["coverage_summary"],
            )
            await self.progress_service.append_event(
                session,
                tenant_id=task.tenant_id,
                task_id=task.id,
                event_type="task_completed" if value_of(task.status) == "COMPLETED" else "task_degraded",
                payload_json={"status": value_of(task.status), "message": "任务已完成汇总"},
                plan_version=task.active_plan_version,
            )
            await session.commit()
        return {"next_action": "output"}

    async def fallback_node(self, state: GlobalState) -> dict[str, Any]:
        async with self.session_factory() as session:
            task = await session.scalar(select(SearchTask).where(SearchTask.id == state["task_id"]))
            if task is not None:
                subtasks = list(
                    (
                        await session.scalars(
                            select(Subtask)
                            .where(Subtask.task_id == task.id)
                            .where(Subtask.plan_version == task.active_plan_version)
                        )
                    ).all()
                )
                for item in subtasks:
                    if value_of(item.status) not in {"COMPLETED", "FAILED", "SKIPPED"}:
                        item.status = "FAILED"
                        item.last_error_code = "FALLBACK_UNFINISHED"
                        item.last_error_message = "任务进入降级输出，节点未继续执行。"
                task.status = "DEGRADED"
                task.final_answer = "当前无法稳定完成全部深搜步骤，已返回可用的部分结果。"
                task.control_json = {
                    **json_safe(task.control_json or {}),
                    "waiting_reason": "NONE",
                    "coverage_summary": {"covered": [], "uncovered": ["全部任务"]},
                    "final_citations": [],
                }
                await self.progress_service.append_event(
                    session,
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    event_type="task_degraded",
                    payload_json={"status": "DEGRADED", "message": "进入安全降级输出"},
                    plan_version=task.active_plan_version,
                )
                await session.commit()
        return {"next_action": "output"}

    async def output_node(self, state: GlobalState) -> dict[str, Any]:
        return state

    def route_entry(self, state: GlobalState) -> str:
        return state.get("entry_action", "output")

    def route_by_action(self, state: GlobalState) -> str:
        mapping = {
            "planner": "planner",
            "schedule": "scheduler",
            "clarify": "clarify",
            "step_gate": "step_gate",
            "replan": "replan",
            "finalize": "finalize",
            "fallback": "fallback",
            "output": "output",
        }
        return mapping.get(state.get("next_action", "output"), "output")

    def route_after_scheduler(self, state: GlobalState) -> str:
        return "executor" if int(state.get("ready_count", 0)) > 0 else "step_gate"
