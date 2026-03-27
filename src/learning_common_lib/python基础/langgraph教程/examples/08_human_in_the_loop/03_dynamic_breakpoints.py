"""
08_human_in_the_loop / 03_dynamic_breakpoints

目标:
    使用 interrupt() 函数在节点内部动态中断，仅在特定条件下暂停

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    interrupt() 函数（langgraph.types）

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/08_human_in_the_loop/03_dynamic_breakpoints.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/08_human_in_the_loop/03_dynamic_breakpoints.py

预期现象:
    低风险操作直接执行，高风险操作触发中断等待人工确认

生产提醒:
    动态中断比 interrupt_before/after 更灵活，可根据运行时状态决定是否暂停
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class State(TypedDict, total=False):
    action: str
    risk_level: float
    status: str
    result: str


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------

def risk_assessment(state: State) -> dict:
    """风险评估"""
    action = state.get("action", "")
    # 模拟风险评估
    risk = 0.9 if "删除" in action else 0.3
    print(f"[风险评估] action='{action}', risk={risk}")
    return {"risk_level": risk}


def sensitive_action(state: State) -> dict:
    """敏感操作节点：高风险时动态中断"""
    if state.get("risk_level", 0) > 0.8:
        # 高风险操作，需要人工确认
        human_response = interrupt("此操作风险较高，是否继续？(yes/no)")
        if human_response == "no":
            print("[敏感操作] 用户取消")
            return {"status": "cancelled", "result": "操作已取消"}
        print("[敏感操作] 用户确认，继续执行")
    else:
        print("[敏感操作] 低风险，直接执行")

    return {"status": "executed", "result": f"操作完成: {state.get('action', '')}"}


def report(state: State) -> dict:
    """生成报告"""
    print(f"[报告] status={state.get('status')}, result={state.get('result')}")
    return {}


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------

builder = StateGraph(State)
builder.add_node("risk_assessment", risk_assessment)
builder.add_node("sensitive_action", sensitive_action)
builder.add_node("report", report)

builder.add_edge(START, "risk_assessment")
builder.add_edge("risk_assessment", "sensitive_action")
builder.add_edge("sensitive_action", "report")
builder.add_edge("report", END)

memory = MemorySaver()
graph = builder.compile(checkpointer=memory)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 场景 1：低风险操作 — 直接通过
    print("=== 场景 1：低风险操作 ===")
    config1 = {"configurable": {"thread_id": "low-risk"}}
    result = graph.invoke({"action": "查询数据"}, config1)
    print(f"结果: {result}\n")

    # 场景 2：高风险操作 — 触发中断
    print("=== 场景 2：高风险操作（触发中断）===")
    config2 = {"configurable": {"thread_id": "high-risk"}}
    result = graph.invoke({"action": "删除全部数据"}, config2)
    print(f"中断时状态: {result}")

    # 人工确认后恢复
    print("\n=== 人工确认：同意继续 ===")
    result = graph.invoke(Command(resume="yes"), config2)
    print(f"最终结果: {result}")
