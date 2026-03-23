"""Planner logic for the deep search minimum demo."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

try:
    from ..domain.clarify_rules import maybe_build_preplan_clarification
    from ..domain.contracts import ClarificationRequest, PlanNodeSpec
    from ..domain.dag import (
        QueryProfile,
        ReplanHint,
        build_dag_fingerprint,
        build_plan_nodes,
        detect_query_profile,
    )
except ImportError:
    from 最小可执行demo.domain.clarify_rules import maybe_build_preplan_clarification
    from 最小可执行demo.domain.contracts import ClarificationRequest, PlanNodeSpec
    from 最小可执行demo.domain.dag import (
        QueryProfile,
        ReplanHint,
        build_dag_fingerprint,
        build_plan_nodes,
        detect_query_profile,
    )


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlanOutcome:
    profile: QueryProfile
    resolved_query: str
    plan_nodes: list[PlanNodeSpec]
    dag_fingerprint: str
    clarification_request: ClarificationRequest | None = None
    replan_hint: ReplanHint | None = None


class PlanService:
    @staticmethod
    def _build_replan_hint(replan_context: dict[str, Any] | None) -> ReplanHint | None:
        if not replan_context:
            return None
        trigger = dict(replan_context.get("trigger") or {})
        failed_subtasks = tuple(
            sorted(
                str(item.get("code") or "").strip()
                for item in list(replan_context.get("failed_subtasks") or [])
                if str(item.get("code") or "").strip()
            )
        )
        completed_subtasks = tuple(
            sorted(
                str(item.get("code") or "").strip()
                for item in list(replan_context.get("completed_subtasks") or [])
                if str(item.get("code") or "").strip()
            )
        )
        attempt_no = max(1, int(replan_context.get("attempt_no") or 1))
        reason = str(
            trigger.get("message")
            or trigger.get("reason")
            or replan_context.get("reason")
            or "上一轮计划未能稳定收敛"
        ).strip()
        gap_type = trigger.get("gap_type")
        return ReplanHint(
            attempt_no=attempt_no,
            reason=reason,
            gap_type=str(gap_type) if gap_type else None,
            failed_subtasks=failed_subtasks,
            completed_subtasks=completed_subtasks,
        )

    def create_plan(
        self,
        *,
        original_query: str,
        resolved_query: str | None = None,
        allow_clarify: bool = True,
        replan_context: dict[str, Any] | None = None,
    ) -> PlanOutcome:
        effective_query = (resolved_query or original_query).strip()
        profile = detect_query_profile(effective_query)
        replan_hint = self._build_replan_hint(replan_context)
        clarification_request = None
        if allow_clarify and replan_hint is None:
            clarification_request = maybe_build_preplan_clarification(effective_query, profile)
        plan_nodes = build_plan_nodes(effective_query, profile, replan_hint=replan_hint)
        dag_fingerprint = build_dag_fingerprint(plan_nodes)
        logger.info(
            "plan created intent=%s clarify=%s nodes=%s fingerprint=%s replan=%s",
            profile.intent,
            clarification_request is not None,
            len(plan_nodes),
            dag_fingerprint[:12],
            replan_hint.attempt_no if replan_hint is not None else 0,
        )
        return PlanOutcome(
            profile=profile,
            resolved_query=effective_query,
            plan_nodes=plan_nodes,
            dag_fingerprint=dag_fingerprint,
            clarification_request=clarification_request,
            replan_hint=replan_hint,
        )
