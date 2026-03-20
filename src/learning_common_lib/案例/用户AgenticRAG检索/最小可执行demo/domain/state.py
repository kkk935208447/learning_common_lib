"""LangGraph state schemas for the deepsearch demo."""

from __future__ import annotations

from typing import Literal, TypedDict


class GlobalState(TypedDict, total=False):
    entry_action: Literal["intake", "planner", "step_gate", "finalize", "fallback", "output"]
    task_id: int
    request_id: str
    session_id: str
    tenant_id: str
    user_id: str
    original_query: str
    resolved_query: str
    active_plan_version: int
    global_iteration: int
    replan_count: int
    clarification_count: int
    waiting_reason: Literal["NONE", "SUBTASKS", "CLARIFICATION"]
    clarification_source: Literal["PREPLAN", "STEP_GATE"] | None
    latest_result_ref: dict
    clarification_ref: dict | None
    pending_resume_execution_id: str | None
    historical_fingerprints: list[str]
    next_action: Literal["schedule", "replan", "clarify", "finalize", "fallback", "output"]
    final_answer: str | None
    error: str | None


class SubtaskState(TypedDict, total=False):
    task_id: int
    plan_version: int
    subtask_code: str
    execution_id: str
    task_type: Literal["RETRIEVAL", "REASONING", "REFLECTION"]
    query: str
    route_hints: list[str]
    iteration: int
    max_iterations: int
    global_evidence_refs: list[str]
    global_evidence_payloads: list[dict]
    working_evidence_refs: list[str]
    working_evidence: list[dict]
    retrieval_hits: list[dict]
    evidence_drafts: list[dict]
    eval_summary: dict
    draft_text: str
    verify_summary: dict
    filters: dict
    verify_retry_count: int
    status: Literal["COMPLETED", "ESCALATED"]
    next_action: Literal["cache", "rewrite", "retrieve", "retry", "draft", "verify", "complete", "escalate"]
