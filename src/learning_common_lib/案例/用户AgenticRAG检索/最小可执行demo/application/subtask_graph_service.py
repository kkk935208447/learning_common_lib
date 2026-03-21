"""LangGraph-based subtask execution loop for the first demo."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import get_settings
from ..domain.contracts import EvidenceCardDraft, KnowledgeChunkHit, SubtaskResultEnvelope
from ..domain.scoring import passes_threshold, score_evidence_cards
from ..domain.state import SubtaskState
from .common import json_safe, utcnow, value_of
from .progress_service import ProgressService

try:
    from ..infrastructure.models import EvidenceCard, SearchTask, Subtask, SubtaskRun
except ImportError:
    from 最小可执行demo.infrastructure.models import EvidenceCard, SearchTask, Subtask, SubtaskRun


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

    async def cache_probe_node(self, state: SubtaskState) -> dict[str, Any]:
        if state.get("task_type") == "REASONING" and state.get("global_evidence_payloads"):
            return {
                "next_action": "draft",
                "evidence_drafts": state.get("global_evidence_payloads", []),
            }
        return {"next_action": "rewrite"}

    async def rewrite_node(self, state: SubtaskState) -> dict[str, Any]:
        query = state["query"]
        iteration = int(state.get("iteration", 0))
        if iteration > 0:
            query = f"{query} 补充检索"
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
        return {
            "retrieval_hits": [hit.model_dump(mode="json") for hit in top_hits],
            "evidence_drafts": [draft.model_dump(mode="json") for draft in drafts],
        }

    async def evaluate_node(self, state: SubtaskState) -> dict[str, Any]:
        drafts = [EvidenceCardDraft.model_validate(item) for item in state.get("evidence_drafts", [])]
        return {"eval_summary": score_evidence_cards(drafts)}

    async def retry_search_node(self, state: SubtaskState) -> dict[str, Any]:
        return {"iteration": int(state.get("iteration", 0)) + 1}

    async def draft_node(self, state: SubtaskState) -> dict[str, Any]:
        drafts = [EvidenceCardDraft.model_validate(item) for item in state.get("evidence_drafts", [])]
        if state.get("task_type") == "REASONING" and drafts:
            prompt = {
                "kind": "reasoning_summary",
                "query": state["query"],
                "evidence": [item.model_dump(mode="json") for item in drafts[: get_settings().final_evidence_top_k]],
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
        return {"draft_text": draft_text}

    async def verify_node(self, state: SubtaskState) -> dict[str, Any]:
        draft_text = state.get("draft_text", "")
        drafts = state.get("evidence_drafts", [])
        retry_count = int(state.get("verify_retry_count", 0))
        invalid_sensitive = any(token in draft_text for token in ("身份证", "银行卡", "密码"))
        citations_ok = bool(drafts) or bool(state.get("global_evidence_refs"))
        factual_ok = bool(draft_text.strip()) and citations_ok
        return {
            "verify_summary": {
                "factual_ok": factual_ok,
                "citations_ok": citations_ok,
                "sensitive_ok": not invalid_sensitive,
                "retry_count": retry_count,
            }
        }

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
        evidence_count = len(state.get("evidence_drafts", []))
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
                await session.commit()
                return None

            run.status = "RUNNING"
            run.started_at = utcnow()
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
        global_evidence_payloads: list[dict[str, Any]] = []
        reuse_global_evidence = value_of(subtask.task_type) == "REASONING"
        if reuse_global_evidence:
            cached_pool = await self.evidence_service.load_evidence_pool(task.request_id, run.plan_version)
            if cached_pool:
                global_evidence_refs = [str(item["card_uid"]) for item in cached_pool[:8]]
                global_evidence_payloads = [json_safe(item) for item in cached_pool[:8]]
            else:
                async with self.session_factory() as session:
                    cards = list(
                        (
                            await session.scalars(
                                select(EvidenceCard)
                                .where(EvidenceCard.task_id == run.task_id)
                                .where(EvidenceCard.plan_version == run.plan_version)
                                .order_by(EvidenceCard.created_at.asc())
                            )
                        ).all()
                    )
                    global_evidence_refs = [card.card_uid for card in cards[:8]]
                    global_evidence_payloads = [
                        {
                            "claim": card.claim,
                            "source_type": value_of(card.source_type),
                            "document_id": card.source_locator_json.get("document_id"),
                            "version_id": card.source_locator_json.get("version_id"),
                            "chunk_uid": card.source_locator_json.get("chunk_uid"),
                            "retrieval_score": float(card.retrieval_score or 0.0),
                            "confidence": float(card.confidence or 0.0),
                            "claim_type": value_of(card.claim_type),
                            "payload_json": card.payload_json or {},
                            "card_uid": card.card_uid,
                        }
                        for card in cards[:8]
                    ]

        result = await self.graph.ainvoke(
            {
                "task_id": run.task_id,
                "plan_version": run.plan_version,
                "subtask_code": run.subtask_code,
                "execution_id": execution_id,
                "task_type": value_of(subtask.task_type),
                "query": f"{task.resolved_query or task.original_query}。子任务：{subtask.description}",
                "route_hints": subtask.route_hints_json or [],
                "iteration": 0,
                "max_iterations": int(subtask.max_iterations or 2),
                "global_evidence_refs": global_evidence_refs,
                "global_evidence_payloads": global_evidence_payloads,
                "working_evidence_refs": [],
            }
        )

        eval_summary = json_safe(result.get("eval_summary", {}))
        verify_summary = json_safe(result.get("verify_summary", {}))
        evidence_drafts = json_safe(result.get("evidence_drafts", []))
        draft_text = result.get("draft_text")
        evidence_card_refs = list(global_evidence_refs) if reuse_global_evidence else [f"EC-{execution_id}-{item['chunk_uid']}" for item in evidence_drafts]

        if result.get("status") == "COMPLETED":
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
                usage_stats={"llm_tokens": max(1, len((draft_text or "").split())) * 8, "retrieval_calls": 0 if value_of(subtask.task_type) == "REASONING" else 2, "elapsed_ms": 200, "cache_hits": 0},
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

        await self.evidence_service.stage_subtask_memory(
            execution_id,
            {
                "task_id": run.task_id,
                "plan_version": run.plan_version,
                "subtask_code": run.subtask_code,
                "query": f"{task.resolved_query or task.original_query}。子任务：{subtask.description}",
                "task_type": value_of(subtask.task_type),
                "retrieval_hits": json_safe(result.get("retrieval_hits", [])),
                "evidence_drafts": evidence_drafts,
                "eval_summary": eval_summary,
                "verify_summary": verify_summary,
                "draft_text": draft_text,
                "global_evidence_refs": global_evidence_refs,
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
        return envelope
