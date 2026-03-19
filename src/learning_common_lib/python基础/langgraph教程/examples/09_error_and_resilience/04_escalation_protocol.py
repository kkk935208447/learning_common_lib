from __future__ import annotations

"""
目标: 子任务升级到全局循环，5 种升级触发条件
关键 API: EscalationReport 结构化升级报告
运行命令: python 04_escalation_protocol.py
预期现象: 子任务根据不同失败原因生成升级报告，全局循环根据报告决定后续动作
生产提醒: 升级协议是 AgenticRAG 容错的核心，确保子任务失败不会静默丢失
"""

import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph


# ---------------------------------------------------------------------------
# 升级报告
# ---------------------------------------------------------------------------

class EscalationReport(TypedDict):
    subtask_code: str
    reason: str       # "max_retries" | "permanent_error" | "budget_exceeded" | "quality_insufficient" | "dependency_failed"
    detail: str
    suggested_action: str  # "replan" | "skip" | "manual"


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class SubtaskState(TypedDict, total=False):
    code: str
    description: str
    retry_count: int
    max_retries: int
    budget_used: float
    budget_limit: float
    quality_score: float
    dependency_met: bool
    result: str
    escalation: EscalationReport | None


class GlobalState(TypedDict, total=False):
    subtasks: list[dict]
    escalations: Annotated[list[EscalationReport], operator.add]
    completed: Annotated[list[str], operator.add]
    global_action: str


# ---------------------------------------------------------------------------
# 子任务节点
# ---------------------------------------------------------------------------

def execute_subtask(state: SubtaskState) -> dict:
    """执行子任务，检查各种失败条件"""
    code = state.get("code", "")
    retry = state.get("retry_count", 0)
    budget = state.get("budget_used", 0)
    budget_limit = state.get("budget_limit", 10.0)
    quality = state.get("quality_score", 0)
    dep_met = state.get("dependency_met", True)

    print(f"[子任务 {code}] 执行检查...")

    # 检查 5 种升级条件
    if not dep_met:
        return {"escalation": {
            "subtask_code": code, "reason": "dependency_failed",
            "detail": "前置依赖未满足", "suggested_action": "replan",
        }}
    if retry >= state.get("max_retries", 3):
        return {"escalation": {
            "subtask_code": code, "reason": "max_retries",
            "detail": f"已重试 {retry} 次", "suggested_action": "skip",
        }}
    if budget > budget_limit:
        return {"escalation": {
            "subtask_code": code, "reason": "budget_exceeded",
            "detail": f"预算 {budget}/{budget_limit}", "suggested_action": "skip",
        }}
    if 0 < quality < 0.6:
        return {"escalation": {
            "subtask_code": code, "reason": "quality_insufficient",
            "detail": f"质量分 {quality}", "suggested_action": "replan",
        }}

    # 成功
    print(f"[子任务 {code}] 成功")
    return {"result": f"{code} 完成", "escalation": None}


# ---------------------------------------------------------------------------
# 全局节点
# ---------------------------------------------------------------------------

def dispatcher(state: GlobalState) -> dict:
    """分发子任务并收集结果"""
    subtasks = state.get("subtasks", [])
    escalations: list[EscalationReport] = []
    completed: list[str] = []

    sub_graph = _build_subtask_graph()

    for task_def in subtasks:
        sub_input: SubtaskState = {
            "code": task_def["code"],
            "description": task_def.get("description", ""),
            "retry_count": task_def.get("retry_count", 0),
            "max_retries": task_def.get("max_retries", 3),
            "budget_used": task_def.get("budget_used", 0),
            "budget_limit": task_def.get("budget_limit", 10),
            "quality_score": task_def.get("quality_score", 0),
            "dependency_met": task_def.get("dependency_met", True),
        }
        result = sub_graph.invoke(sub_input)
        if result.get("escalation"):
            escalations.append(result["escalation"])
        else:
            completed.append(result.get("result", ""))

    return {"escalations": escalations, "completed": completed}


def handle_escalations(state: GlobalState) -> dict:
    """处理升级报告"""
    escalations = state.get("escalations", [])
    if not escalations:
        print("[全局] 无升级，全部完成")
        return {"global_action": "done"}

    for esc in escalations:
        print(f"[升级] {esc['subtask_code']}: {esc['reason']} → {esc['suggested_action']}")

    # 根据升级建议决定全局动作
    actions = {e["suggested_action"] for e in escalations}
    if "replan" in actions:
        return {"global_action": "replan"}
    if "manual" in actions:
        return {"global_action": "manual"}
    return {"global_action": "done"}


def global_route(state: GlobalState) -> Literal["dispatcher", "__end__"]:
    if state.get("global_action") == "replan":
        return "dispatcher"
    return "__end__"


# ---------------------------------------------------------------------------
# 子任务图
# ---------------------------------------------------------------------------

def _build_subtask_graph() -> StateGraph:
    b = StateGraph(SubtaskState)
    b.add_node("execute", execute_subtask)
    b.add_edge(START, "execute")
    b.add_edge("execute", END)
    return b.compile()


# ---------------------------------------------------------------------------
# 全局图
# ---------------------------------------------------------------------------

builder = StateGraph(GlobalState)
builder.add_node("dispatcher", dispatcher)
builder.add_node("handle_escalations", handle_escalations)
builder.add_edge(START, "dispatcher")
builder.add_edge("dispatcher", "handle_escalations")
builder.add_conditional_edges("handle_escalations", global_route)

graph = builder.compile()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    initial: GlobalState = {
        "subtasks": [
            {"code": "S1", "description": "正常任务", "dependency_met": True},
            {"code": "S2", "description": "重试耗尽", "retry_count": 5, "max_retries": 3},
            {"code": "S3", "description": "预算超限", "budget_used": 15, "budget_limit": 10},
            {"code": "S4", "description": "依赖缺失", "dependency_met": False},
            {"code": "S5", "description": "质量不足", "quality_score": 0.3},
        ],
        "escalations": [],
        "completed": [],
        "global_action": "",
    }
    result = graph.invoke(initial)
    print(f"\n完成: {result.get('completed')}")
    print(f"升级数: {len(result.get('escalations', []))}")
    print(f"全局动作: {result.get('global_action')}")
