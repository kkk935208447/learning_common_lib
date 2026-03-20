from __future__ import annotations

"""
目标: 使用 interrupt_before 在节点执行前暂停，等待人工确认后继续
关键 API: interrupt_before, Command(resume=...)
运行命令: python 01_interrupt_before.py
预期现象: 图执行到 sensitive_node 前暂停，模拟人工确认后恢复执行
生产提醒: 需要 checkpointer（如 MemorySaver）保存中断点状态，生产环境建议用持久化存储
"""

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class State(TypedDict, total=False):
    query: str
    validated: bool
    result: str


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------

def prepare(state: State) -> dict:
    """准备阶段"""
    print(f"[准备] 收到查询: {state.get('query', '')}")
    return {"validated": False}


def sensitive_node(state: State) -> dict:
    """敏感操作节点 — 执行前需要人工确认"""
    print("[敏感操作] 执行中...")
    return {"result": "敏感操作已完成", "validated": True}


def finalize(state: State) -> dict:
    """最终处理"""
    print(f"[完成] validated={state.get('validated')}")
    return {}


# ---------------------------------------------------------------------------
# 构建图 — interrupt_before 指定在 sensitive_node 前暂停
# ---------------------------------------------------------------------------

builder = StateGraph(State)
builder.add_node("prepare", prepare)
builder.add_node("sensitive_node", sensitive_node)
builder.add_node("finalize", finalize)

builder.add_edge(START, "prepare")
builder.add_edge("prepare", "sensitive_node")
builder.add_edge("sensitive_node", "finalize")
builder.add_edge("finalize", END)

# MemorySaver 作为 checkpointer，interrupt_before 指定暂停点
memory = MemorySaver()
graph = builder.compile(
    checkpointer=memory,
    interrupt_before=["sensitive_node"],  # 在此节点前暂停
)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    config = {"configurable": {"thread_id": "demo-1"}}

    # 第一次调用：执行到 sensitive_node 前暂停
    print("=== 第一次调用（将在 sensitive_node 前暂停）===")
    result = graph.invoke({"query": "执行敏感操作"}, config)
    print(f"暂停时状态: {result}")

    # 查看当前状态
    snapshot = graph.get_state(config)
    print(f"下一个待执行节点: {snapshot.next}")

    # 模拟人工确认：使用 Command(resume=...) 恢复
    print("\n=== 人工确认后恢复执行 ===")
    # 直接调用 invoke(None) 恢复执行（不修改状态）
    result = graph.invoke(None, config)
    print(f"最终状态: {result}")
