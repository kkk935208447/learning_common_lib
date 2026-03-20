"""Clarify detection and option builders for the first demo."""

from __future__ import annotations

from datetime import datetime, timedelta

from .contracts import ClarificationOption, ClarificationRequest
from .dag_templates import QueryProfile


def maybe_build_preplan_clarification(query: str, profile: QueryProfile) -> ClarificationRequest | None:
    if profile.needs_time_range:
        return ClarificationRequest(
            question="请选择你关心的时间范围",
            options=[
                ClarificationOption(id="opt_30d", label="近 30 天"),
                ClarificationOption(id="opt_90d", label="近 90 天"),
            ],
            default_option_id="opt_90d",
            clarification_source="PREPLAN",
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            reason_code="missing_time_range",
        )
    if profile.needs_baseline:
        return ClarificationRequest(
            question="请选择本次比较的基线方式",
            options=[
                ClarificationOption(id="opt_latest", label="与当前制度对比"),
                ClarificationOption(id="opt_prev", label="与上一版制度对比"),
            ],
            default_option_id="opt_latest",
            clarification_source="PREPLAN",
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            reason_code="missing_baseline",
        )
    if "哪些" in query and "部门" in query:
        return ClarificationRequest(
            question="请选择你希望优先关注的范围",
            options=[
                ClarificationOption(id="opt_all", label="全部范围"),
                ClarificationOption(id="opt_core", label="核心制度范围"),
            ],
            default_option_id="opt_all",
            clarification_source="PREPLAN",
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            reason_code="missing_object_scope",
        )
    return None


def apply_clarification_to_query(query: str, clarification_request: dict | None, selected_option_id: str | None) -> str:
    if not clarification_request or not selected_option_id:
        return query

    option_labels = {
        option["id"]: option["label"]
        for option in clarification_request.get("options", [])
    }
    label = option_labels.get(selected_option_id)
    if not label:
        return query
    return f"{query}，补充约束：{label}"
