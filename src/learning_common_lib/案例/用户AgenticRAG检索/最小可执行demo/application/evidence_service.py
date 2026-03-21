"""Evidence staging, persistence, and final answer assembly."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.contracts import EvidenceCardDraft, FinalAnswerInput, KnowledgeChunkHit
from ..infrastructure.settings import get_settings
from .common import json_safe, utcnow, value_of

try:
    from ..infrastructure.models import EvidenceCard, SearchTask, Subtask, SubtaskRun
except ImportError:
    from 最小可执行demo.infrastructure.models import EvidenceCard, SearchTask, Subtask, SubtaskRun


class EvidenceService:
    def __init__(self, redis_runtime, llm) -> None:
        self.redis_runtime = redis_runtime
        self.llm = llm
        self.settings = get_settings()

    @staticmethod
    def build_evidence_pool_key(request_id: str, plan_version: int) -> str:
        return f"{request_id}:{plan_version}"

    def build_evidence_drafts(
        self,
        *,
        task_id: int,
        plan_version: int,
        subtask_code: str,
        hits: list[KnowledgeChunkHit],
    ) -> list[EvidenceCardDraft]:
        drafts: list[EvidenceCardDraft] = []
        for hit in hits:
            claim = hit.content.strip().replace("\n", " ")
            claim = claim[:240] if claim else f"{subtask_code} 命中文档片段"
            drafts.append(
                EvidenceCardDraft(
                    claim=claim,
                    source_type=hit.source_type,
                    document_id=int(hit.document_id) if hit.document_id is not None else None,
                    version_id=hit.version_id,
                    chunk_uid=hit.chunk_uid,
                    retrieval_score=round(hit.score, 3),
                    confidence=round(min(0.95, 0.45 + (hit.score / 2.0)), 3),
                    payload_json={
                        "task_id": task_id,
                        "plan_version": plan_version,
                        "subtask_code": subtask_code,
                        "content": hit.content,
                        "metadata": hit.metadata,
                        "locator": hit.locator,
                    },
                )
            )
        return drafts

    @staticmethod
    def build_hot_evidence_items(
        *,
        execution_id: str,
        subtask_code: str,
        drafts: list[dict[str, Any]] | list[EvidenceCardDraft],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for raw in drafts:
            draft = raw if isinstance(raw, EvidenceCardDraft) else EvidenceCardDraft.model_validate(raw)
            items.append(
                {
                    "card_uid": f"EC-{execution_id}-{draft.chunk_uid}",
                    "claim": draft.claim,
                    "source_type": draft.source_type,
                    "document_id": draft.document_id,
                    "version_id": draft.version_id,
                    "chunk_uid": draft.chunk_uid,
                    "retrieval_score": draft.retrieval_score,
                    "confidence": draft.confidence,
                    "claim_type": draft.claim_type,
                    "produced_by_subtask": subtask_code,
                    "payload_json": json_safe(draft.payload_json),
                }
            )
        return items

    async def stage_payload(self, execution_id: str, payload: dict[str, Any]) -> None:
        await self.redis_runtime.save_json("run_payload", execution_id, json_safe(payload), ttl_seconds=3600)

    async def load_staged_payload(self, execution_id: str) -> dict[str, Any] | None:
        return await self.redis_runtime.load_json("run_payload", execution_id)

    async def delete_staged_payload(self, execution_id: str) -> None:
        await self.redis_runtime.delete_json("run_payload", execution_id)

    async def stage_subtask_memory(self, execution_id: str, payload: dict[str, Any]) -> None:
        await self.redis_runtime.save_json(
            "subtask_memory",
            execution_id,
            json_safe(payload),
            ttl_seconds=self.settings.subtask_memory_ttl_seconds,
        )

    async def load_subtask_memory(self, execution_id: str) -> dict[str, Any] | None:
        return await self.redis_runtime.load_json("subtask_memory", execution_id)

    async def append_evidence_pool_items(self, request_id: str, plan_version: int, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        key = self.build_evidence_pool_key(request_id, plan_version)
        existing = await self.redis_runtime.load_json("evidence_pool", key)
        if not isinstance(existing, dict):
            existing = {}
        for item in items:
            existing[str(item["card_uid"])] = json_safe(item)
        await self.redis_runtime.save_json(
            "evidence_pool",
            key,
            existing,
            ttl_seconds=self.settings.evidence_pool_ttl_seconds,
        )

    async def replace_evidence_pool_items(self, request_id: str, plan_version: int, items: list[dict[str, Any]]) -> None:
        key = self.build_evidence_pool_key(request_id, plan_version)
        if not items:
            await self.redis_runtime.delete_json("evidence_pool", key)
            return
        payload = {str(item["card_uid"]): json_safe(item) for item in items}
        await self.redis_runtime.save_json(
            "evidence_pool",
            key,
            payload,
            ttl_seconds=self.settings.evidence_pool_ttl_seconds,
        )

    async def load_evidence_pool(self, request_id: str, plan_version: int) -> list[dict[str, Any]]:
        key = self.build_evidence_pool_key(request_id, plan_version)
        payload = await self.redis_runtime.load_json("evidence_pool", key)
        if not isinstance(payload, dict):
            return []
        return [json_safe(item) for item in payload.values()]

    async def promote_evidence_drafts_to_hot_pool(
        self,
        *,
        request_id: str,
        plan_version: int,
        execution_id: str,
        subtask_code: str,
        drafts: list[dict[str, Any]] | list[EvidenceCardDraft],
    ) -> int:
        items = self.build_hot_evidence_items(
            execution_id=execution_id,
            subtask_code=subtask_code,
            drafts=drafts,
        )
        await self.append_evidence_pool_items(request_id, plan_version, items)
        return len(items)

    async def build_evidence_pool_items_from_db(
        self,
        session: AsyncSession,
        *,
        task_id: int,
        plan_version: int,
    ) -> list[dict[str, Any]]:
        cards = list(
            (
                await session.scalars(
                    select(EvidenceCard)
                    .where(EvidenceCard.task_id == task_id)
                    .where(EvidenceCard.plan_version == plan_version)
                    .order_by(EvidenceCard.created_at.asc())
                )
            ).all()
        )
        return [
            {
                "card_uid": card.card_uid,
                "claim": card.claim,
                "source_type": value_of(card.source_type),
                "document_id": card.source_locator_json.get("document_id"),
                "version_id": card.source_locator_json.get("version_id"),
                "chunk_uid": card.source_locator_json.get("chunk_uid"),
                "retrieval_score": float(card.retrieval_score or 0.0),
                "confidence": float(card.confidence or 0.0),
                "claim_type": value_of(card.claim_type),
                "produced_by_subtask": card.produced_by_subtask,
                "payload_json": card.payload_json or {},
            }
            for card in cards
        ]

    async def load_plan_evidence_records(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        task_id: int,
        plan_version: int,
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for item in await self.load_evidence_pool(request_id, plan_version):
            card_uid = str(item.get("card_uid") or "")
            if not card_uid:
                continue
            merged[card_uid] = json_safe(item)
        for item in await self.build_evidence_pool_items_from_db(
            session,
            task_id=task_id,
            plan_version=plan_version,
        ):
            merged[str(item["card_uid"])] = json_safe(item)
        records = list(merged.values())
        records.sort(
            key=lambda item: (
                -float(item.get("retrieval_score") or 0.0),
                str(item.get("card_uid") or ""),
            )
        )
        return records

    async def sync_evidence_pool_from_db(
        self,
        session_factory,
        *,
        task_id: int,
        request_id: str,
        plan_version: int,
    ) -> int:
        async with session_factory() as session:
            items = await self.build_evidence_pool_items_from_db(
                session,
                task_id=task_id,
                plan_version=plan_version,
            )
        await self.replace_evidence_pool_items(request_id, plan_version, items)
        return len(items)

    async def flush_staged_payload(self, session: AsyncSession, execution_id: str) -> dict[str, Any]:
        payload = await self.load_staged_payload(execution_id)
        if not payload:
            run = await session.scalar(select(SubtaskRun).where(SubtaskRun.execution_id == execution_id))
            if run is not None:
                if value_of(run.data_plane_flush_status) == "FLUSHED":
                    return {
                        "inserted": 0,
                        "task_id": run.task_id,
                        "request_id": None,
                        "plan_version": run.plan_version,
                    }
                run.data_plane_flush_status = "FAILED"
                await session.flush()
            return {"inserted": 0, "task_id": None, "request_id": None, "plan_version": None}

        run = await session.scalar(select(SubtaskRun).where(SubtaskRun.execution_id == execution_id))
        task = await session.scalar(select(SearchTask).where(SearchTask.id == payload.get("task_id")))
        subtask = None
        if run is None:
            return {
                "inserted": 0,
                "task_id": payload.get("task_id"),
                "request_id": payload.get("request_id"),
                "plan_version": payload.get("plan_version"),
                "orphaned": True,
            }
        if task is None:
            run.data_plane_flush_status = "FAILED"
            await session.flush()
            return {"inserted": 0, "task_id": None, "request_id": None, "plan_version": None}
        if value_of(run.status) in {"FAILED", "STALE_IGNORED"}:
            run.data_plane_flush_status = "FAILED"
            await session.flush()
            return {
                "inserted": 0,
                "task_id": run.task_id,
                "request_id": payload.get("request_id"),
                "plan_version": run.plan_version,
                "stale": True,
            }
        subtask = await session.scalar(
            select(Subtask)
            .where(Subtask.task_id == run.task_id)
            .where(Subtask.plan_version == run.plan_version)
            .where(Subtask.subtask_code == run.subtask_code)
        )
        if (
            int(task.active_plan_version or 0) != run.plan_version
            or subtask is None
            or subtask.current_execution_id != execution_id
        ):
            run.data_plane_flush_status = "FAILED"
            await session.flush()
            return {
                "inserted": 0,
                "task_id": run.task_id,
                "request_id": payload.get("request_id"),
                "plan_version": run.plan_version,
                "stale": True,
            }
        if value_of(run.data_plane_flush_status) == "FLUSHED":
            return {
                "inserted": 0,
                "task_id": payload.get("task_id"),
                "request_id": payload.get("request_id"),
                "plan_version": payload.get("plan_version"),
            }

        inserted = 0
        run.data_plane_flush_status = "FLUSHING"
        await session.flush()
        try:
            for item in payload.get("evidence_cards", []):
                card_uid = f"EC-{execution_id}-{item['chunk_uid']}"
                exists = await session.scalar(select(EvidenceCard).where(EvidenceCard.card_uid == card_uid))
                if exists is not None:
                    continue
                payload_json = item.get("payload_json", {})
                locator = payload_json.get("locator", {})
                document_id = item.get("document_id")
                version_id = item["version_id"]
                chunk_uid = item["chunk_uid"]
                session.add(
                    EvidenceCard(
                        card_uid=card_uid,
                        tenant_id=payload["tenant_id"],
                        task_id=payload["task_id"],
                        plan_version=payload["plan_version"],
                        produced_by_subtask=payload["subtask_code"],
                        claim=item["claim"],
                        claim_type=item.get("claim_type", "DESCRIPTIVE"),
                        source_id=f"{document_id}:{version_id}:{chunk_uid}",
                        source_type=item["source_type"],
                        source_locator_json={
                            "kb_code": payload.get("kb_code", "default"),
                            "document_id": document_id,
                            "version_id": version_id,
                            "chunk_uid": chunk_uid,
                            **locator,
                        },
                        reliability_tier="T1",
                        data_freshness=utcnow().date(),
                        retrieval_score=item["retrieval_score"],
                        confidence=item["confidence"],
                        corroborated_by_json=[],
                        conflicts_with_json=[],
                        payload_json=payload_json,
                        created_at=utcnow(),
                    )
                )
                inserted += 1
            run.data_plane_flush_status = "FLUSHED"
            await session.flush()
        except Exception:
            run.data_plane_flush_status = "FAILED"
            await session.flush()
            raise
        return {
            "inserted": inserted,
            "task_id": payload["task_id"],
            "request_id": payload["request_id"],
            "plan_version": payload["plan_version"],
        }

    async def build_final_answer_input(self, session: AsyncSession, task_id: int, plan_version: int) -> FinalAnswerInput:
        task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
        if task is None:
            return FinalAnswerInput(
                completed_subtasks=[],
                global_evidence_refs=[],
                conflict_summary=None,
                uncovered_points=[],
                degraded_reason="TASK_NOT_FOUND",
            )
        subtasks = list(
            (
                await session.scalars(
                    select(Subtask)
                    .where(Subtask.task_id == task_id)
                    .where(Subtask.plan_version == plan_version)
                    .order_by(Subtask.priority.asc(), Subtask.subtask_code.asc())
                )
            ).all()
        )
        records = await self.load_plan_evidence_records(
            session,
            request_id=task.request_id,
            task_id=task_id,
            plan_version=plan_version,
        )
        completed = [item.subtask_code for item in subtasks if value_of(item.status) == "COMPLETED"]
        uncovered = [item.subtask_code for item in subtasks if value_of(item.status) not in {"COMPLETED", "SKIPPED"}]
        return FinalAnswerInput(
            completed_subtasks=completed,
            global_evidence_refs=[str(item["card_uid"]) for item in records],
            conflict_summary=None,
            uncovered_points=uncovered,
            degraded_reason=None,
        )

    async def assemble_final_answer(self, session: AsyncSession, task_id: int, plan_version: int) -> dict[str, Any]:
        task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
        if task is None:
            return {
                "answer": "任务不存在",
                "citations": [],
                "coverage_summary": {"covered": [], "uncovered": []},
                "final_input": {},
            }

        final_input = await self.build_final_answer_input(session, task_id, plan_version)
        control_json = json_safe(task.control_json or {})
        postexec_focus = str(control_json.get("postexec_focus") or "")
        subtasks = list(
            (
                await session.scalars(
                    select(Subtask)
                    .where(Subtask.task_id == task_id)
                    .where(Subtask.plan_version == plan_version)
                    .order_by(Subtask.priority.asc(), Subtask.subtask_code.asc())
                )
            ).all()
        )
        records = await self.load_plan_evidence_records(
            session,
            request_id=task.request_id,
            task_id=task_id,
            plan_version=plan_version,
        )
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in records:
            produced_by = str(
                item.get("produced_by_subtask")
                or (item.get("payload_json") or {}).get("subtask_code")
                or "UNKNOWN"
            )
            grouped[produced_by].append(item)

        findings_by_subtask: dict[str, str] = {}
        covered: list[str] = []
        for subtask_code, items in grouped.items():
            covered.append(subtask_code)
            findings_by_subtask[subtask_code] = "；".join(str(item.get("claim") or "")[:100] for item in items[:2])

        findings: list[str] = []
        for item in subtasks:
            if value_of(item.status) != "COMPLETED":
                continue
            if item.subtask_code not in covered:
                covered.append(item.subtask_code)
            if item.key_findings:
                findings.append(f"{item.subtask_code}: {item.key_findings[:320]}")
                continue
            if item.subtask_code in findings_by_subtask:
                findings.append(f"{item.subtask_code}: {findings_by_subtask[item.subtask_code]}")

        prompt = {
            "kind": "final_answer",
            "findings": findings,
            "citations": [str(item["card_uid"]) for item in records[:6]],
            "uncovered": final_input.uncovered_points,
            "focus": postexec_focus or None,
        }
        llm_response = await self.llm.generate(prompt, structured_schema="final_answer")
        structured_output = llm_response.get("structured_output") or {}
        answer = structured_output.get("answer") or "\n".join(findings) or "未产出稳定结论"
        if postexec_focus == "opt_policy" and not answer.startswith("回答口径：制度解释优先"):
            answer = f"回答口径：制度解释优先\n{answer}"
        elif postexec_focus == "opt_change" and not answer.startswith("回答口径：变更摘要优先"):
            answer = f"回答口径：变更摘要优先\n{answer}"
        valid_citations = [str(item["card_uid"]) for item in records[:6]]
        valid_citation_set = set(valid_citations)
        raw_citations = list(structured_output.get("citations") or valid_citations)
        citations = [citation for citation in raw_citations if citation in valid_citation_set]
        if not citations:
            citations = valid_citations
        return {
            "answer": answer,
            "citations": citations,
            "coverage_summary": {
                "covered": covered,
                "uncovered": final_input.uncovered_points,
            },
            "final_input": final_input.model_dump(mode="json"),
        }
