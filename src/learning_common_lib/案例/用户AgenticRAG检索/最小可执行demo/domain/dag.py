"""Planner templates and deterministic DAG helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

try:
    from .contracts import PlanDependency, PlanNodeSpec
except ImportError:
    from 最小可执行demo.domain.contracts import PlanDependency, PlanNodeSpec


@dataclass(slots=True)
class QueryProfile:
    intent: str
    complexity: str
    risk: str
    needs_time_range: bool = False
    needs_object_scope: bool = False
    needs_baseline: bool = False


@dataclass(slots=True)
class ReplanHint:
    attempt_no: int
    reason: str
    gap_type: str | None = None
    failed_subtasks: tuple[str, ...] = ()
    completed_subtasks: tuple[str, ...] = ()


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


def _build_default_plan_nodes(resolved_query: str, profile: QueryProfile) -> list[PlanNodeSpec]:
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


def _build_replan_simple_fact_nodes(resolved_query: str, replan_hint: ReplanHint) -> list[PlanNodeSpec]:
    if replan_hint.attempt_no <= 1:
        return [
            PlanNodeSpec(
                subtask_code="ST-001",
                description=f"复核 `{resolved_query}` 的基础事实证据，优先复用已稳定结论",
                task_type="RETRIEVAL",
                route_hints=["vector", "search", "carry_forward"],
                acceptance_criteria={"min_sources": 2, "need_citations": True},
                budget_slice={"llm_tokens": 1000, "retrieval_calls": 4},
                priority=1,
            ),
            PlanNodeSpec(
                subtask_code="ST-002",
                description=f"围绕上轮缺口补检 `{resolved_query}` 的补充事实与版本差异：{replan_hint.reason}",
                task_type="RETRIEVAL",
                route_hints=["vector", "search", "gap_recovery"],
                acceptance_criteria={"min_sources": 2, "need_citations": True},
                budget_slice={"llm_tokens": 1400, "retrieval_calls": 6},
                priority=2,
            ),
            PlanNodeSpec(
                subtask_code="ST-003",
                description=f"综合复核后的证据，收敛 `{resolved_query}` 的最终答案",
                task_type="REASONING",
                depends_on=[
                    PlanDependency(code="ST-001"),
                    PlanDependency(code="ST-002"),
                ],
                route_hints=["evidence_only", "replan_v1"],
                acceptance_criteria={"min_sources": 2, "need_citations": True},
                budget_slice={"llm_tokens": 1800, "retrieval_calls": 0},
                priority=3,
            ),
        ]

    return [
        PlanNodeSpec(
            subtask_code="ST-001",
            description=f"再次核对 `{resolved_query}` 的基础事实证据",
            task_type="RETRIEVAL",
            route_hints=["vector", "search", "carry_forward"],
            acceptance_criteria={"min_sources": 2, "need_citations": True},
            budget_slice={"llm_tokens": 1000, "retrieval_calls": 4},
            priority=1,
        ),
        PlanNodeSpec(
            subtask_code="ST-002",
            description=f"扩展检索 `{resolved_query}` 的补充事实与边界条件",
            task_type="RETRIEVAL",
            route_hints=["vector", "search", "gap_recovery"],
            acceptance_criteria={"min_sources": 2, "need_citations": True},
            budget_slice={"llm_tokens": 1400, "retrieval_calls": 6},
            priority=2,
        ),
        PlanNodeSpec(
            subtask_code="ST-003",
            description=f"对 `{resolved_query}` 的残余缺口做反思校验：{replan_hint.reason}",
            task_type="REFLECTION",
            depends_on=[
                PlanDependency(code="ST-001"),
                PlanDependency(code="ST-002"),
            ],
            route_hints=["evidence_only", "reflection"],
            acceptance_criteria={"min_sources": 2, "need_citations": True},
            budget_slice={"llm_tokens": 1200, "retrieval_calls": 0},
            priority=3,
        ),
        PlanNodeSpec(
            subtask_code="ST-004",
            description=f"综合反思后的证据，输出 `{resolved_query}` 的最终答案",
            task_type="REASONING",
            depends_on=[
                PlanDependency(code="ST-001"),
                PlanDependency(code="ST-002"),
                PlanDependency(code="ST-003"),
            ],
            route_hints=["evidence_only", "replan_v2"],
            acceptance_criteria={"min_sources": 2, "need_citations": True},
            budget_slice={"llm_tokens": 1800, "retrieval_calls": 0},
            priority=4,
        ),
    ]


def _build_replan_complex_nodes(resolved_query: str, replan_hint: ReplanHint) -> list[PlanNodeSpec]:
    failure_tags = "、".join(replan_hint.failed_subtasks[:3]) or "上一轮失败节点"
    if replan_hint.attempt_no <= 1:
        return [
            PlanNodeSpec(
                subtask_code="ST-001",
                description=f"复核 `{resolved_query}` 的基础规则与关键定义，延续已稳定主线",
                task_type="RETRIEVAL",
                route_hints=["vector", "search", "carry_forward"],
                acceptance_criteria={"min_sources": 2, "need_citations": True},
                budget_slice={"llm_tokens": 1200, "retrieval_calls": 4},
                priority=1,
            ),
            PlanNodeSpec(
                subtask_code="ST-002",
                description=f"补检 `{resolved_query}` 的变化依据、对比口径与补充佐证",
                task_type="RETRIEVAL",
                route_hints=["vector", "search", "comparison"],
                acceptance_criteria={"min_sources": 2, "need_citations": True},
                budget_slice={"llm_tokens": 1400, "retrieval_calls": 4},
                priority=2,
            ),
            PlanNodeSpec(
                subtask_code="ST-003",
                description=f"围绕 {failure_tags} 做定向缺口恢复检索：{replan_hint.reason}",
                task_type="RETRIEVAL",
                route_hints=["vector", "search", "gap_recovery"],
                acceptance_criteria={"min_sources": 2, "need_citations": True},
                budget_slice={"llm_tokens": 1600, "retrieval_calls": 6},
                priority=3,
            ),
            PlanNodeSpec(
                subtask_code="ST-004",
                description=f"综合复核后的证据，形成 `{resolved_query}` 的重规划汇总结论",
                task_type="REASONING",
                depends_on=[
                    PlanDependency(code="ST-001"),
                    PlanDependency(code="ST-002"),
                    PlanDependency(code="ST-003"),
                ],
                route_hints=["evidence_only", "replan_v1"],
                acceptance_criteria={"min_sources": 3, "need_citations": True},
                budget_slice={"llm_tokens": 2200, "retrieval_calls": 0},
                priority=4,
            ),
        ]

    return [
        PlanNodeSpec(
            subtask_code="ST-001",
            description=f"再次核对 `{resolved_query}` 的基础规则与关键定义",
            task_type="RETRIEVAL",
            route_hints=["vector", "search", "carry_forward"],
            acceptance_criteria={"min_sources": 2, "need_citations": True},
            budget_slice={"llm_tokens": 1200, "retrieval_calls": 4},
            priority=1,
        ),
        PlanNodeSpec(
            subtask_code="ST-002",
            description=f"再次补检 `{resolved_query}` 的变化依据与补充佐证",
            task_type="RETRIEVAL",
            route_hints=["vector", "search", "comparison"],
            acceptance_criteria={"min_sources": 2, "need_citations": True},
            budget_slice={"llm_tokens": 1400, "retrieval_calls": 4},
            priority=2,
        ),
        PlanNodeSpec(
            subtask_code="ST-003",
            description=f"继续围绕 {failure_tags} 做扩展缺口恢复检索",
            task_type="RETRIEVAL",
            route_hints=["vector", "search", "gap_recovery"],
            acceptance_criteria={"min_sources": 2, "need_citations": True},
            budget_slice={"llm_tokens": 1800, "retrieval_calls": 6},
            priority=3,
        ),
        PlanNodeSpec(
            subtask_code="ST-004",
            description=f"对 `{resolved_query}` 的残余冲突与证据边界做反思校验",
            task_type="REFLECTION",
            depends_on=[
                PlanDependency(code="ST-001"),
                PlanDependency(code="ST-002"),
                PlanDependency(code="ST-003"),
            ],
            route_hints=["evidence_only", "reflection"],
            acceptance_criteria={"min_sources": 3, "need_citations": True},
            budget_slice={"llm_tokens": 1600, "retrieval_calls": 0},
            priority=4,
        ),
        PlanNodeSpec(
            subtask_code="ST-005",
            description=f"综合反思后的证据，收敛 `{resolved_query}` 的最终答案",
            task_type="REASONING",
            depends_on=[
                PlanDependency(code="ST-001"),
                PlanDependency(code="ST-002"),
                PlanDependency(code="ST-003"),
                PlanDependency(code="ST-004"),
            ],
            route_hints=["evidence_only", "replan_v2"],
            acceptance_criteria={"min_sources": 3, "need_citations": True},
            budget_slice={"llm_tokens": 2200, "retrieval_calls": 0},
            priority=5,
        ),
    ]


def build_plan_nodes(
    resolved_query: str,
    profile: QueryProfile,
    *,
    replan_hint: ReplanHint | None = None,
) -> list[PlanNodeSpec]:
    if replan_hint is None:
        return _build_default_plan_nodes(resolved_query, profile)
    if profile.intent == "simple_fact":
        return _build_replan_simple_fact_nodes(resolved_query, replan_hint)
    return _build_replan_complex_nodes(resolved_query, replan_hint)


def build_dag_fingerprint(plan_nodes: list[PlanNodeSpec]) -> str:
    raw = json.dumps(
        [node.model_dump(mode="json") for node in plan_nodes],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
