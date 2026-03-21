"""Planner logic for the deep search minimum demo."""

from __future__ import annotations

import logging
from dataclasses import dataclass

try:
    from ..domain.clarify_rules import maybe_build_preplan_clarification
    from ..domain.contracts import ClarificationRequest, PlanNodeSpec
    from ..domain.dag import QueryProfile, build_dag_fingerprint, build_plan_nodes, detect_query_profile
except ImportError:
    from 最小可执行demo.domain.clarify_rules import maybe_build_preplan_clarification
    from 最小可执行demo.domain.contracts import ClarificationRequest, PlanNodeSpec
    from 最小可执行demo.domain.dag import QueryProfile, build_dag_fingerprint, build_plan_nodes, detect_query_profile


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlanOutcome:
    profile: QueryProfile
    resolved_query: str
    plan_nodes: list[PlanNodeSpec]
    dag_fingerprint: str
    clarification_request: ClarificationRequest | None = None


class PlanService:
    def create_plan(
        self,
        *,
        original_query: str,
        resolved_query: str | None = None,
        allow_clarify: bool = True,
    ) -> PlanOutcome:
        effective_query = (resolved_query or original_query).strip()
        profile = detect_query_profile(effective_query)
        clarification_request = None
        if allow_clarify:
            clarification_request = maybe_build_preplan_clarification(effective_query, profile)
        plan_nodes = build_plan_nodes(effective_query, profile)
        dag_fingerprint = build_dag_fingerprint(plan_nodes)
        logger.info(
            "plan created intent=%s clarify=%s nodes=%s fingerprint=%s",
            profile.intent,
            clarification_request is not None,
            len(plan_nodes),
            dag_fingerprint[:12],
        )
        return PlanOutcome(
            profile=profile,
            resolved_query=effective_query,
            plan_nodes=plan_nodes,
            dag_fingerprint=dag_fingerprint,
            clarification_request=clarification_request,
        )
