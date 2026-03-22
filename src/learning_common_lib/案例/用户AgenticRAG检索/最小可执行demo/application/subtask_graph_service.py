"""LangGraph-based subtask execution loop for the first demo."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.contracts import EvidenceCardDraft, KnowledgeChunkHit, SubtaskResultEnvelope
from ..domain.scoring import passes_threshold, score_evidence_cards
from ..domain.state_machine import SubtaskState
from ..infrastructure.settings import get_settings
from .common import json_safe, utcnow, value_of
from .progress_service import ProgressService

try:
    from ..infrastructure.models import SearchTask, Subtask, SubtaskRun
except ImportError:
    from 最小可执行demo.infrastructure.models import SearchTask, Subtask, SubtaskRun


logger = logging.getLogger(__name__)


class SubtaskGraphService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        vector_reader,
        search_reader,
        projection_reader,
        llm,
        evidence_service,
        progress_service: ProgressService,
    ) -> None:
        self.session_factory = session_factory
        self.vector_reader = vector_reader
        self.search_reader = search_reader
        self.projection_reader = projection_reader
        self.llm = llm
        self.evidence_service = evidence_service
        self.progress_service = progress_service
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(SubtaskState)
        graph.add_node("cache_probe", self.cache_probe_node)
        graph.add_node("rewrite", self.rewrite_node)
        graph.add_node("retrieve", self.retrieve_node)
        graph.add_node("evaluate", self.evaluate_node)
        graph.add_node("retry_search", self.retry_search_node)
        graph.add_node("draft", self.draft_node)
        graph.add_node("verify", self.verify_node)
        graph.add_node("retry_answer", self.retry_answer_node)
        graph.add_node("complete", self.complete_node)
        graph.add_node("escalate", self.escalate_node)

        graph.add_edge(START, "cache_probe")
        graph.add_conditional_edges("cache_probe", self.route_after_cache)
        graph.add_edge("rewrite", "retrieve")
        graph.add_edge("retrieve", "evaluate")
        graph.add_conditional_edges("evaluate", self.route_after_evaluate)
        graph.add_edge("retry_search", "rewrite")
        graph.add_edge("draft", "verify")
        graph.add_conditional_edges("verify", self.route_after_verify)
        graph.add_edge("retry_answer", "draft")
        graph.add_edge("complete", END)
        graph.add_edge("escalate", END)
        return graph.compile()

    async def _load_memory(self, execution_id: str) -> dict[str, Any]:
        return json_safe(await self.evidence_service.load_subtask_memory(execution_id) or {})

    async def _update_memory(self, execution_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        payload = await self._load_memory(execution_id)
        payload.update(json_safe(patch))
        await self.evidence_service.stage_subtask_memory(execution_id, payload)
        return payload

    async def _load_global_evidence_payloads(
        self,
        *,
        execution_id: str,
        plan_version: int,
        refs: list[str],
    ) -> list[dict[str, Any]]:
        if not refs:
            return []
        memory = await self._load_memory(execution_id)
        request_id = str(memory.get("request_id") or "")
        if not request_id:
            return []
        records = await self.evidence_service.load_evidence_pool(request_id, plan_version)
        by_uid = {str(item.get("card_uid") or ""): json_safe(item) for item in records}
        return [by_uid[card_uid] for card_uid in refs if card_uid in by_uid]

    async def cache_probe_node(self, state: SubtaskState) -> dict[str, Any]:
        if state.get("task_type") in {"REASONING", "REFLECTION"} and state.get("global_evidence_refs"):
            return {"next_action": "draft"}
        return {"next_action": "rewrite"}

    async def rewrite_node(self, state: SubtaskState) -> dict[str, Any]:
        query = state["query"]
        iteration = int(state.get("iteration", 0))
        route_hints = {str(item) for item in list(state.get("route_hints") or [])}
        hint_suffixes: list[str] = []
        if "comparison" in route_hints:
            hint_suffixes.append("补充关键词：版本差异 对比 上一版")
        if "gap_recovery" in route_hints:
            hint_suffixes.append("补充关键词：缺口恢复 补充佐证 例外条件")
        if "carry_forward" in route_hints:
            hint_suffixes.append("补充关键词：核心规则 关键定义 生效口径")
        if iteration > 0:
            hint_suffixes.append("补充检索")
        if hint_suffixes:
            query = f"{query} {' '.join(hint_suffixes)}"
        return {"query": query}

    async def retrieve_node(self, state: SubtaskState) -> dict[str, Any]:
        settings = get_settings()
        filters = await self.projection_reader.build_retrieval_filters(state["task_id"])
        vector_hits = [
            KnowledgeChunkHit.model_validate(item)
            for item in await self.vector_reader.search(state["query"], top_k=settings.vector_top_k, filters=filters)
        ]
        search_hits = [
            KnowledgeChunkHit.model_validate(item)
            for item in await self.search_reader.search(state["query"], top_k=settings.search_top_k, filters=filters)
        ]
        merged: dict[str, KnowledgeChunkHit] = {}
        for hit in vector_hits + search_hits:
            existing = merged.get(hit.chunk_uid)
            if existing is None or hit.score > existing.score:
                merged[hit.chunk_uid] = hit
        top_hits = sorted(merged.values(), key=lambda item: item.score, reverse=True)[: settings.merged_top_k]
        drafts = self.evidence_service.build_evidence_drafts(
            task_id=state["task_id"],
            plan_version=state["plan_version"],
            subtask_code=state["subtask_code"],
            hits=top_hits,
        )
        await self._update_memory(
            state["execution_id"],
            {
                "retrieval_hits": [hit.model_dump(mode="json") for hit in top_hits],
                "evidence_drafts": [draft.model_dump(mode="json") for draft in drafts],
            },
        )
        return {
            "working_memory_ref": {
                "namespace": "subtask_memory",
                "key": state["execution_id"],
                "evidence_count": len(drafts),
            }
        }

    async def evaluate_node(self, state: SubtaskState) -> dict[str, Any]:
        memory = await self._load_memory(state["execution_id"])
        drafts = [EvidenceCardDraft.model_validate(item) for item in memory.get("evidence_drafts", [])]
        eval_summary = score_evidence_cards(drafts)
        await self._update_memory(state["execution_id"], {"eval_summary": eval_summary})
        return {"eval_summary": eval_summary}

    async def retry_search_node(self, state: SubtaskState) -> dict[str, Any]:
        return {"iteration": int(state.get("iteration", 0)) + 1}

    async def draft_node(self, state: SubtaskState) -> dict[str, Any]:
        memory = await self._load_memory(state["execution_id"])
        drafts = [EvidenceCardDraft.model_validate(item) for item in memory.get("evidence_drafts", [])]
        if state.get("task_type") in {"REASONING", "REFLECTION"}:
            hot_records = await self._load_global_evidence_payloads(
                execution_id=state["execution_id"],
                plan_version=state["plan_version"],
                refs=list(state.get("global_evidence_refs", [])),
            )
            prompt = {
                "kind": "reasoning_summary",
                "query": state["query"],
                "evidence": hot_records[: get_settings().final_evidence_top_k],
            }
            llm_response = await self.llm.generate(prompt, structured_schema="reasoning_summary")
            structured = llm_response.get("structured_output") or {}
            draft_text = structured.get("answer") or llm_response.get("text", "")
        elif not drafts and state.get("global_evidence_refs"):
            draft_text = f"基于已有全局证据回答子任务 {state['subtask_code']}"
        else:
            prompt = {"kind": "draft_answer", "evidence": [item.model_dump(mode="json") for item in drafts[:4]]}
            llm_response = await self.llm.generate(prompt, structured_schema="draft_answer")
            structured = llm_response.get("structured_output") or {}
            draft_text = structured.get("answer") or llm_response.get("text", "")
        await self._update_memory(state["execution_id"], {"draft_text": draft_text})
        return {}

    async def verify_node(self, state: SubtaskState) -> dict[str, Any]:
        memory = await self._load_memory(state["execution_id"])
        draft_text = str(memory.get("draft_text") or "")
        drafts = list(memory.get("evidence_drafts") or [])
        retry_count = int(state.get("verify_retry_count", 0))
        invalid_sensitive = any(token in draft_text for token in ("身份证", "银行卡", "密码"))
        citations_ok = bool(drafts) or bool(state.get("global_evidence_refs"))
        factual_ok = bool(draft_text.strip()) and citations_ok
        verify_summary = {
            "factual_ok": factual_ok,
            "citations_ok": citations_ok,
            "sensitive_ok": not invalid_sensitive,
            "retry_count": retry_count,
        }
        await self._update_memory(state["execution_id"], {"verify_summary": verify_summary})
        return {"verify_summary": verify_summary}

    async def retry_answer_node(self, state: SubtaskState) -> dict[str, Any]:
        return {"verify_retry_count": int(state.get("verify_retry_count", 0)) + 1}

    async def complete_node(self, state: SubtaskState) -> dict[str, Any]:
        return {"status": "COMPLETED"}

    async def escalate_node(self, state: SubtaskState) -> dict[str, Any]:
        return {"status": "ESCALATED"}

    def route_after_cache(self, state: SubtaskState) -> str:
        return "draft" if state.get("next_action") == "draft" else "rewrite"

    def route_after_evaluate(self, state: SubtaskState) -> str:
        eval_summary = state.get("eval_summary", {})
        evidence_count = 0
        working_memory_ref = state.get("working_memory_ref") or {}
        if isinstance(working_memory_ref, dict):
            evidence_count = int(working_memory_ref.get("evidence_count", 0) or 0)
        if passes_threshold(eval_summary, min_sources=2, evidence_count=evidence_count):
            return "draft"
        if int(state.get("iteration", 0)) + 1 < int(state.get("max_iterations", 2)):
            return "retry_search"
        return "escalate"

    def route_after_verify(self, state: SubtaskState) -> str:
        verify_summary = state.get("verify_summary", {})
        if verify_summary.get("factual_ok") and verify_summary.get("citations_ok") and verify_summary.get("sensitive_ok"):
            return "complete"
        if int(verify_summary.get("retry_count", 0)) < 1:
            return "retry_answer"
        return "escalate"

    @staticmethod
    def _should_request_step_gate_clarification(
        *,
        task: SearchTask,
        subtask: Subtask,
        global_evidence_refs: list[str],
    ) -> bool:
        if value_of(subtask.task_type) != "REASONING" or len(global_evidence_refs) < 2:
            return False
        control_json = json_safe(task.control_json or {})
        if control_json.get("postexec_focus"):
            return False
        query_text = f"{task.resolved_query or task.original_query}".strip()
        return any(token in query_text for token in ("口径", "优先", "侧重", "重点", "更关注"))

    async def execute(self, *, execution_id: str) -> SubtaskResultEnvelope | None:
        async with self.session_factory() as session:
            run = await session.scalar(select(SubtaskRun).where(SubtaskRun.execution_id == execution_id).with_for_update())
            if run is None:
                return None
            if value_of(run.status) not in {"CLAIMED", "DISPATCHED"}:
                return None
            task = await session.scalar(select(SearchTask).where(SearchTask.id == run.task_id).with_for_update())
            subtask = await session.scalar(
                select(Subtask)
                .where(Subtask.task_id == run.task_id)
                .where(Subtask.plan_version == run.plan_version)
                .where(Subtask.subtask_code == run.subtask_code)
                .with_for_update()
            )
            if task is None or subtask is None:
                return None
            if subtask.current_execution_id != execution_id or int(task.active_plan_version or 0) != run.plan_version:
                run.status = "STALE_IGNORED"
                run.finished_at = utcnow()
                await self.progress_service.append_event(
                    session,
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    event_type="subtask_stale_ignored",
                    payload_json={
                        "status": value_of(task.status),
                        "message": f"{subtask.subtask_code} 旧执行结果已忽略",
                    },
                    plan_version=run.plan_version,
                    subtask_code=subtask.subtask_code,
                    execution_id=execution_id,
                )
                await session.commit()
                return None

            run.status = "RUNNING"
            run.started_at = utcnow()
            logger.info(
                "subtask execution started task_id=%s execution_id=%s subtask_code=%s",
                run.task_id,
                execution_id,
                run.subtask_code,
            )
            await self.progress_service.append_event(
                session,
                tenant_id=task.tenant_id,
                task_id=task.id,
                event_type="subtask_started",
                payload_json={"status": "WAITING_SUBTASKS", "message": f"{subtask.subtask_code} 开始执行"},
                plan_version=run.plan_version,
                subtask_code=subtask.subtask_code,
                execution_id=execution_id,
            )
            await session.commit()

        global_evidence_refs: list[str] = []
        reuse_global_evidence = value_of(subtask.task_type) in {"REASONING", "REFLECTION"}
        if reuse_global_evidence:
            async with self.session_factory() as session:
                records = await self.evidence_service.load_plan_evidence_records(
                    session,
                    request_id=task.request_id,
                    task_id=run.task_id,
                    plan_version=run.plan_version,
                )
            global_evidence_refs = [str(item["card_uid"]) for item in records[:8]]

        query = f"{task.resolved_query or task.original_query}。子任务：{subtask.description}"
        await self.evidence_service.stage_subtask_memory(
            execution_id,
            {
                "request_id": task.request_id,
                "task_id": run.task_id,
                "plan_version": run.plan_version,
                "subtask_code": run.subtask_code,
                "query": query,
                "task_type": value_of(subtask.task_type),
                "retrieval_hits": [],
                "evidence_drafts": [],
                "eval_summary": {},
                "verify_summary": {},
                "draft_text": "",
                "global_evidence_refs": global_evidence_refs,
            },
        )

        result = await self.graph.ainvoke(
            {
                "task_id": run.task_id,
                "plan_version": run.plan_version,
                "subtask_code": run.subtask_code,
                "execution_id": execution_id,
                "task_type": value_of(subtask.task_type),
                "query": query,
                "route_hints": subtask.route_hints_json or [],
                "iteration": 0,
                "max_iterations": int(subtask.max_iterations or 2),
                "working_memory_ref": {"namespace": "subtask_memory", "key": execution_id},
                "global_evidence_refs": global_evidence_refs,
            }
        )

        memory = await self._load_memory(execution_id)
        eval_summary = json_safe(result.get("eval_summary", {}))
        verify_summary = json_safe(result.get("verify_summary", {}))
        evidence_drafts = json_safe(memory.get("evidence_drafts", []))
        draft_text = str(memory.get("draft_text") or "")
        evidence_card_refs = list(global_evidence_refs) if reuse_global_evidence else [f"EC-{execution_id}-{item['chunk_uid']}" for item in evidence_drafts]
        if self._should_request_step_gate_clarification(
            task=task,
            subtask=subtask,
            global_evidence_refs=global_evidence_refs,
        ):
            if not eval_summary:
                eval_summary = {
                    "coverage": 1.0 if global_evidence_refs else 0.0,
                    "confidence": 0.7,
                    "conflict": 0.0,
                    "total_score": 0.7,
                    "gap_type": "user_input_gap",
                }
            else:
                eval_summary = {
                    **eval_summary,
                    "gap_type": "user_input_gap",
                }
            envelope = SubtaskResultEnvelope(
                task_id=run.task_id,
                plan_version=run.plan_version,
                subtask_code=run.subtask_code,
                execution_id=execution_id,
                status="ESCALATED",
                result_ref={"execution_id": execution_id},
                evidence_card_refs=evidence_card_refs,
                output_text=draft_text,
                verify_summary=verify_summary,
                eval_summary=eval_summary,
                usage_stats={
                    "llm_tokens": max(1, len((draft_text or "").split())) * 8,
                    "retrieval_calls": 0,
                    "elapsed_ms": 200,
                    "cache_hits": 0,
                },
                escalation_report={
                    "reason": "needs_user_input",
                    "suggested_global_action": "clarify",
                    "best_score": float(eval_summary.get("total_score", 0.0)),
                    "gap_type": "user_input_gap",
                    "message": "已有足够证据，但需要用户指定最终回答的呈现口径。",
                    "evidence_card_refs": evidence_card_refs[:6],
                },
            )
        elif result.get("status") == "COMPLETED":
            envelope = SubtaskResultEnvelope(
                task_id=run.task_id,
                plan_version=run.plan_version,
                subtask_code=run.subtask_code,
                execution_id=execution_id,
                status="COMPLETED",
                result_ref={"execution_id": execution_id},
                evidence_card_refs=evidence_card_refs,
                output_text=draft_text,
                verify_summary=verify_summary,
                eval_summary=eval_summary,
                usage_stats={"llm_tokens": max(1, len((draft_text or "").split())) * 8, "retrieval_calls": 0 if value_of(subtask.task_type) in {"REASONING", "REFLECTION"} else 2, "elapsed_ms": 200, "cache_hits": 0},
            )
        else:
            gap_type = eval_summary.get("gap_type", "insufficient_evidence")
            suggested_action = "clarify" if gap_type == "user_input_gap" else "replan"
            envelope = SubtaskResultEnvelope(
                task_id=run.task_id,
                plan_version=run.plan_version,
                subtask_code=run.subtask_code,
                execution_id=execution_id,
                status="ESCALATED",
                result_ref={"execution_id": execution_id},
                evidence_card_refs=[],
                output_text=draft_text,
                verify_summary=verify_summary,
                eval_summary=eval_summary,
                usage_stats={"llm_tokens": 400, "retrieval_calls": 2, "elapsed_ms": 200, "cache_hits": 0},
                escalation_report={
                    "reason": "insufficient_evidence" if suggested_action == "replan" else "needs_user_input",
                    "suggested_global_action": suggested_action,
                    "best_score": float(eval_summary.get("total_score", 0.0)),
                    "gap_type": str(gap_type),
                    "message": "局部补检后证据仍然不足，交给全局控制面处理。",
                    "evidence_card_refs": [],
                },
            )

        await self.evidence_service.stage_payload(
            execution_id,
            {
                "tenant_id": task.tenant_id,
                "task_id": run.task_id,
                "request_id": task.request_id,
                "plan_version": run.plan_version,
                "subtask_code": run.subtask_code,
                "kb_code": task.kb_code,
                "evidence_cards": [] if reuse_global_evidence else evidence_drafts,
            },
        )
        if not reuse_global_evidence and evidence_drafts:
            await self.evidence_service.promote_evidence_drafts_to_hot_pool(
                request_id=task.request_id,
                plan_version=run.plan_version,
                execution_id=execution_id,
                subtask_code=run.subtask_code,
                drafts=evidence_drafts,
            )
        logger.info(
            "subtask execution finished task_id=%s execution_id=%s status=%s evidence_refs=%s",
            run.task_id,
            execution_id,
            envelope.status,
            len(envelope.evidence_card_refs),
        )
        return envelope
