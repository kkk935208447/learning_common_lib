"""
09_error_and_resilience / 04_escalation_protocol

目标:
    子任务升级到全局循环，5 种升级触发条件

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    EscalationReport 结构化升级报告

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/09_error_and_resilience/04_escalation_protocol.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/09_error_and_resilience/04_escalation_protocol.py

预期现象:
    子任务根据不同失败原因生成升级报告，全局循环根据报告决定后续动作

生产提醒:
    升级协议是 AgenticRAG 容错的核心，确保子任务失败不会静默丢失
"""
from __future__ import annotations

from typing import Literal, TypedDict

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
    escalations: list[EscalationReport]
    completed: list[str]
    global_action: str
    replan_count: int
    max_replans: int


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
    replan_count = state.get("replan_count", 0)
    escalations: list[EscalationReport] = []
    completed: list[str] = []

    sub_graph = _build_subtask_graph()

    for task_def in subtasks:
        adjusted_quality = task_def.get("quality_score", 0)
        adjusted_dependency = task_def.get("dependency_met", True)

        # 演示重规划后的修复效果：第二轮修复依赖和质量问题。
        if replan_count >= 1 and task_def["code"] in {"S4", "S5"}:
            adjusted_dependency = True
            adjusted_quality = 0.9

        sub_input: SubtaskState = {
            "code": task_def["code"],
            "description": task_def.get("description", ""),
            "retry_count": task_def.get("retry_count", 0),
            "max_retries": task_def.get("max_retries", 3),
            "budget_used": task_def.get("budget_used", 0),
            "budget_limit": task_def.get("budget_limit", 10),
            "quality_score": adjusted_quality,
            "dependency_met": adjusted_dependency,
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
    replan_count = state.get("replan_count", 0)
    max_replans = state.get("max_replans", 1)
    if not escalations:
        print("[全局] 无升级，全部完成")
        return {"global_action": "done"}

    for esc in escalations:
        print(f"[升级] {esc['subtask_code']}: {esc['reason']} → {esc['suggested_action']}")

    # 根据升级建议决定全局动作
    actions = {e["suggested_action"] for e in escalations}
    if "replan" in actions and replan_count < max_replans:
        print(f"[全局] 触发重规划 ({replan_count + 1}/{max_replans})")
        return {"global_action": "replan", "replan_count": replan_count + 1}
    if "replan" in actions:
        print("[全局] 已达到最大重规划次数，进入人工处理")
        return {"global_action": "manual"}
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
builder.add_conditional_edges("handle_escalations", global_route, {"dispatcher": "dispatcher", "__end__": END})

graph = builder.compile()

def get_langgraph_png(app: StateGraph, file_name: str) -> None:
    from pathlib import Path
    PARENT_DIR = Path(__file__).resolve().parent   # 获得当前文件的父目录
    FILE_PATH = str(PARENT_DIR / file_name)
    app.get_graph(xray=True).draw_mermaid_png(output_file_path=FILE_PATH)
    print(f"图已导出到 {FILE_PATH}")

# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    get_langgraph_png(graph, "04_escalation_protocol.png") # 导出图

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
        "replan_count": 0,
        "max_replans": 1,
    }
    result = graph.invoke(initial)
    print(f"\n完成: {result.get('completed')}")
    print(f"升级数: {len(result.get('escalations', []))}")
    print(f"全局动作: {result.get('global_action')}")
