"""Planner templates and deterministic DAG helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .contracts import PlanDependency, PlanNodeSpec


@dataclass(slots=True)
class QueryProfile:
    intent: str
    complexity: str
    risk: str
    needs_time_range: bool = False
    needs_object_scope: bool = False
    needs_baseline: bool = False


def detect_query_profile(query: str) -> QueryProfile:
    lowered = query.lower()
    if any(token in query for token in ("变化", "变更", "最近", "近 ", "近90", "近 90", "policy", "change")):
        return QueryProfile(
            intent="policy_change",
            complexity="medium",
            risk="medium",
            needs_time_range=("近" not in query and "最近" not in query and "90" not in query),
        )
    if any(token in query for token in ("比较", "对比", "差异", "vs")):
        return QueryProfile(
            intent="comparison",
            complexity="medium",
            risk="medium",
            needs_baseline=True,
        )
    if any(token in query for token in ("趋势", "走势", "波动")):
        return QueryProfile(
            intent="trend",
            complexity="medium",
            risk="low",
            needs_time_range=True,
        )
    return QueryProfile(intent="simple_fact", complexity="low", risk="low")


def build_plan_nodes(resolved_query: str, profile: QueryProfile) -> list[PlanNodeSpec]:
    if profile.intent == "simple_fact":
        return [
            PlanNodeSpec(
                subtask_code="ST-001",
                description=f"检索与问题 `{resolved_query}` 直接相关的事实证据",
                task_type="RETRIEVAL",
                route_hints=["vector", "search"],
                acceptance_criteria={"min_sources": 2, "need_citations": True},
                budget_slice={"llm_tokens": 1000, "retrieval_calls": 4},
            )
        ]

    return [
        PlanNodeSpec(
            subtask_code="ST-001",
            description=f"检索 `{resolved_query}` 的基础规则与关键定义",
            task_type="RETRIEVAL",
            route_hints=["vector", "search"],
            acceptance_criteria={"min_sources": 2, "need_citations": True},
            budget_slice={"llm_tokens": 1200, "retrieval_calls": 4},
            priority=1,
        ),
        PlanNodeSpec(
            subtask_code="ST-002",
            description=f"检索 `{resolved_query}` 的补充佐证、变化依据或对比信息",
            task_type="RETRIEVAL",
            route_hints=["vector", "search"],
            acceptance_criteria={"min_sources": 2, "need_citations": True},
            budget_slice={"llm_tokens": 1200, "retrieval_calls": 4},
            priority=2,
        ),
        PlanNodeSpec(
            subtask_code="ST-003",
            description=f"综合 ST-001 和 ST-002 的证据形成回答骨架：{resolved_query}",
            task_type="REASONING",
            depends_on=[
                PlanDependency(code="ST-001"),
                PlanDependency(code="ST-002"),
            ],
            route_hints=["evidence_only"],
            acceptance_criteria={"min_sources": 2, "need_citations": True},
            budget_slice={"llm_tokens": 1800, "retrieval_calls": 0},
            priority=3,
        ),
    ]


def build_dag_fingerprint(plan_nodes: list[PlanNodeSpec]) -> str:
    raw = "|".join(
        f"{node.subtask_code}:{node.task_type}:{','.join(dep.code for dep in node.depends_on)}"
        for node in plan_nodes
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

