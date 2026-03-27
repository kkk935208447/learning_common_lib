"""
教程与模板共享的结构化契约。

目标:
    教程与模板共享的结构化契约。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    见本文件导入、节点函数和构图代码

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: templates/teaching_contracts.py

运行方式:
    - 通常作为模块导入，不建议单独运行

预期现象:
    运行后可观察本文件对应的状态推进、输出或集成行为

生产提醒:
    - 这些是教学最小形状，不是生产完整 schema
    - 这些契约也不是 LangGraph 框架内置协议
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict


class PlanNodeSpec(TypedDict, total=False):
    """规划器产出的最小计划节点。"""

    node_code: str
    worker_name: str
    objective: str
    route_hints: list[str]
    required_inputs: list[str]
    expected_output: str
    optional: bool


class WorkerTask(TypedDict, total=False):
    """父图交给子图/worker 的最小任务契约。"""

    task_id: str
    plan_node_code: str
    worker_name: str
    objective: str
    context_ref: str | None
    execution_id: str


class EscalationReport(TypedDict, total=False):
    """子图无法自行收敛时上报的结构化升级信息。"""

    worker_name: str
    reason: str
    gap_type: str
    message: str
    suggested_global_action: Literal["continue", "clarify", "replan", "finalize", "fallback"]
    best_score: float | None
    missing_slots: list[str]


class WorkerResultEnvelope(TypedDict, total=False):
    """子图/worker 返回给父图的结果包。"""

    task_id: str
    execution_id: str
    worker_name: str
    status: Literal["COMPLETED", "ESCALATED", "STALE_IGNORED"]
    summary: str
    evidence_refs: list[str]
    output_ref: str | None
    escalation: EscalationReport | None


class ClarificationOption(TypedDict):
    id: str
    label: str


class ClarificationRequest(TypedDict, total=False):
    """结构化 Clarify / 审批请求。"""

    request_id: str
    question: str
    question_type: Literal["SINGLE_SELECT", "MULTI_SELECT"]
    options: list[ClarificationOption]
    clarification_source: str
    default_option_id: str | None
    expires_at: str


class ExecutionRef(TypedDict, total=False):
    """等待恢复时最常用的执行引用。"""

    thread_id: str
    execution_id: str
    plan_version: int
    task_name: str
    subtask_code: str | None


class ResumeEnvelope(TypedDict, total=False):
    """外部 worker 回写给恢复器的最小结果。"""

    thread_id: str
    execution_id: str
    task_id: str
    status: Literal["COMPLETED", "FAILED", "ESCALATED", "STALE_IGNORED"]
    result_payload: dict[str, Any] | None
    result_ref: str | None
    stale_reason: str | None
