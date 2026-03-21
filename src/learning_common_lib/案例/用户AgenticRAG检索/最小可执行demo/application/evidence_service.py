"""Evidence staging, persistence, and final answer assembly."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.contracts import EvidenceCardDraft, FinalAnswerInput, KnowledgeChunkHit
from .common import json_safe, utcnow, value_of

try:
    from ..infrastructure.models import EvidenceCard, SearchTask, Subtask, SubtaskRun
except ImportError:
    from 最小可执行demo.infrastructure.models import EvidenceCard, SearchTask, Subtask, SubtaskRun


class EvidenceService:
    def __init__(self, redis_runtime, llm) -> None:
        self.redis_runtime = redis_runtime
        self.llm = llm

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
                    document_id=int(hit.document_id or 0),
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

    async def stage_payload(self, execution_id: str, payload: dict[str, Any]) -> None:
        await self.redis_runtime.save_json("run_payload", execution_id, json_safe(payload), ttl_seconds=3600)

    async def load_staged_payload(self, execution_id: str) -> dict[str, Any] | None:
        return await self.redis_runtime.load_json("run_payload", execution_id)

    async def delete_staged_payload(self, execution_id: str) -> None:
        await self.redis_runtime.delete_json("run_payload", execution_id)

    async def flush_staged_payload(self, session: AsyncSession, execution_id: str) -> int:
        payload = await self.load_staged_payload(execution_id)
        if not payload:
            run = await session.scalar(select(SubtaskRun).where(SubtaskRun.execution_id == execution_id))
            if run is not None:
                if value_of(run.data_plane_flush_status) == "FLUSHED":
                    return 0
                run.data_plane_flush_status = "FAILED"
                await session.flush()
            return 0

        run = await session.scalar(select(SubtaskRun).where(SubtaskRun.execution_id == execution_id))
        if run is None:
            await self.delete_staged_payload(execution_id)
            return 0
        if value_of(run.data_plane_flush_status) == "FLUSHED":
            await self.delete_staged_payload(execution_id)
            return 0

        inserted = 0
        for item in payload.get("evidence_cards", []):
            card_uid = f"EC-{execution_id}-{item['chunk_uid']}"
            exists = await session.scalar(select(EvidenceCard).where(EvidenceCard.card_uid == card_uid))
            if exists is not None:
                continue
            payload_json = item.get("payload_json", {})
            locator = payload_json.get("locator", {})
            session.add(
                EvidenceCard(
                    card_uid=card_uid,
                    tenant_id=payload["tenant_id"],
                    task_id=payload["task_id"],
                    plan_version=payload["plan_version"],
                    produced_by_subtask=payload["subtask_code"],
                    claim=item["claim"],
                    claim_type=item.get("claim_type", "DESCRIPTIVE"),
                    source_id=f"{item['document_id']}:{item['version_id']}:{item['chunk_uid']}",
                    source_type=item["source_type"],
                    source_locator_json={
                        "kb_code": payload.get("kb_code", "default"),
                        "document_id": item["document_id"],
                        "version_id": item["version_id"],
                        "chunk_uid": item["chunk_uid"],
                        **locator,
                    },
                    reliability_tier="T1",
                    data_freshness=date.today(),
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
        await self.delete_staged_payload(execution_id)
        return inserted

    async def build_final_answer_input(self, session: AsyncSession, task_id: int, plan_version: int) -> FinalAnswerInput:
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
        completed = [item.subtask_code for item in subtasks if value_of(item.status) == "COMPLETED"]
        uncovered = [item.subtask_code for item in subtasks if value_of(item.status) not in {"COMPLETED", "SKIPPED"}]
        return FinalAnswerInput(
            completed_subtasks=completed,
            global_evidence_refs=[card.card_uid for card in cards],
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
        cards = list(
            (
                await session.scalars(
                    select(EvidenceCard)
                    .where(EvidenceCard.task_id == task_id)
                    .where(EvidenceCard.plan_version == plan_version)
                    .order_by(EvidenceCard.retrieval_score.desc(), EvidenceCard.created_at.asc())
                )
            ).all()
        )
        grouped: dict[str, list[EvidenceCard]] = defaultdict(list)
        for card in cards:
            grouped[card.produced_by_subtask].append(card)

        findings_by_subtask: dict[str, str] = {}
        covered: list[str] = []
        for subtask_code, items in grouped.items():
            covered.append(subtask_code)
            findings_by_subtask[subtask_code] = "；".join(card.claim[:100] for card in items[:2])

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
            "citations": [card.card_uid for card in cards[:6]],
            "uncovered": final_input.uncovered_points,
        }
        llm_response = await self.llm.generate(prompt, structured_schema="final_answer")
        structured_output = llm_response.get("structured_output") or {}
        answer = structured_output.get("answer") or "\n".join(findings) or "未产出稳定结论"
        citations = structured_output.get("citations") or [card.card_uid for card in cards[:6]]
        return {
            "answer": answer,
            "citations": citations,
            "coverage_summary": {
                "covered": covered,
                "uncovered": final_input.uncovered_points,
            },
            "final_input": final_input.model_dump(mode="json"),
        }
