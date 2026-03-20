"""Pydantic contracts shared across API, services, and workers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchSubmitRequest(BaseModel):
    session_id: str
    query: str
    kb_code: str = "default"
    scope_json: dict[str, Any] | None = None


class SearchAcceptedResponse(BaseModel):
    request_id: str
    status: str
    snapshot_url: str
    events_url: str


class ClarificationOption(BaseModel):
    id: str
    label: str


class ClarificationRequest(BaseModel):
    question: str
    question_type: Literal["SINGLE_SELECT"] = "SINGLE_SELECT"
    options: list[ClarificationOption]
    default_option_id: str
    clarification_source: Literal["PREPLAN", "STEP_GATE"]
    expires_at: datetime
    reason_code: str


class ClarificationAnswerRequest(BaseModel):
    selected_option_id: str


ClarificationSubmitRequest = ClarificationAnswerRequest


class PlanDependency(BaseModel):
    code: str
    type: Literal["HARD"] = "HARD"


class PlanNodeSpec(BaseModel):
    subtask_code: str
    description: str
    task_type: Literal["RETRIEVAL", "REASONING", "REFLECTION"]
    depends_on: list[PlanDependency] = Field(default_factory=list)
    route_hints: list[str] = Field(default_factory=list)
    acceptance_criteria: dict[str, Any] = Field(default_factory=dict)
    budget_slice: dict[str, Any] = Field(default_factory=dict)
    priority: int = 1


class EscalationReport(BaseModel):
    reason: Literal["needs_user_input", "insufficient_evidence", "conflict_unresolved", "timeout"]
    suggested_global_action: Literal["clarify", "replan", "finalize"]
    best_score: float = 0.0
    gap_type: str
    message: str
    evidence_card_refs: list[str] = Field(default_factory=list)


class SubtaskResultEnvelope(BaseModel):
    task_id: int
    plan_version: int
    subtask_code: str
    execution_id: str
    status: Literal["COMPLETED", "FAILED", "ESCALATED"]
    result_ref: dict[str, Any] | None = None
    evidence_card_refs: list[str] = Field(default_factory=list)
    escalation_report: EscalationReport | None = None
    output_text: str | None = None
    verify_summary: dict[str, Any] = Field(default_factory=dict)
    eval_summary: dict[str, Any] = Field(default_factory=dict)
    usage_stats: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None


class FinalAnswerInput(BaseModel):
    completed_subtasks: list[str]
    global_evidence_refs: list[str]
    conflict_summary: dict[str, Any] | None = None
    uncovered_points: list[str] = Field(default_factory=list)
    degraded_reason: str | None = None


class KnowledgeChunkHit(BaseModel):
    chunk_uid: str
    version_id: int
    document_id: int | None = None
    external_doc_key: str | None = None
    source_type: str
    score: float
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    locator: dict[str, Any] = Field(default_factory=dict)


class EvidenceCardDraft(BaseModel):
    claim: str
    source_type: str
    document_id: int
    version_id: int
    chunk_uid: str
    retrieval_score: float
    confidence: float
    claim_type: str = "DESCRIPTIVE"
    payload_json: dict[str, Any] = Field(default_factory=dict)


class ProgressSummary(BaseModel):
    total_subtasks: int = 0
    completed_subtasks: int = 0
    running_subtasks: int = 0
    waiting_subtasks: int = 0
    current_phase: str = "PENDING"


class TaskEventData(BaseModel):
    request_id: str
    status: str
    message: str
    ts: datetime
    plan_version: int | None = None
    subtask_code: str | None = None
    execution_id: str | None = None


class TaskEventEnvelope(BaseModel):
    id: int
    event: str
    data: TaskEventData


class TaskSnapshotResponse(BaseModel):
    request_id: str
    status: str
    waiting_reason: str | None = None
    active_plan_version: int = 0
    progress_summary: ProgressSummary = Field(default_factory=ProgressSummary)
    clarification_request: ClarificationRequest | None = None
    final_answer: str | None = None
    final_citations: list[str] = Field(default_factory=list)
    coverage_summary: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
