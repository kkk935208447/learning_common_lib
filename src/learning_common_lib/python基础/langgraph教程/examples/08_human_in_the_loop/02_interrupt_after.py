from __future__ import annotations

"""
目标: 使用 interrupt_after 在节点执行后暂停，审核结果后再继续
关键 API: interrupt_after
运行命令: python 02_interrupt_after.py
预期现象: analysis 节点执行后暂停，人工审核结果，可修改状态后继续
生产提醒: interrupt_after 适合需要审核中间结果的场景，如 AI 生成内容的人工审核
"""

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class State(TypedDict, total=False):
    query: str
    analysis: str
    approved: bool
    final_output: str


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------

def analyze(state: State) -> dict:
    """分析节点：生成分析结果供人工审核"""
    query = state.get("query", "")
    print(f"[分析] 处理: {query}")
    return {"analysis": f"对 '{query}' 的分析结果：发现 3 个关键点"}


def publish(state: State) -> dict:
    """发布节点：审核通过后发布"""
    analysis = state.get("analysis", "")
    approved = state.get("approved", False)
    if not approved:
        print("[发布] 未通过审核，跳过发布")
        return {"final_output": "审核未通过，已取消"}
    print(f"[发布] 审核通过，发布: {analysis}")
    return {"final_output": f"已发布: {analysis}"}


# ---------------------------------------------------------------------------
# 构建图 — interrupt_after 在 analyze 后暂停
# ---------------------------------------------------------------------------

builder = StateGraph(State)
builder.add_node("analyze", analyze)
builder.add_node("publish", publish)

builder.add_edge(START, "analyze")
builder.add_edge("analyze", "publish")
builder.add_edge("publish", END)

memory = MemorySaver()
graph = builder.compile(
    checkpointer=memory,
    interrupt_after=["analyze"],  # 分析完成后暂停，等待审核
)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    config = {"configurable": {"thread_id": "review-1"}}

    # 第一次调用：执行 analyze 后暂停
    print("=== 执行分析（完成后暂停）===")
    result = graph.invoke({"query": "LangGraph 人机协作"}, config)
    print(f"分析结果: {result.get('analysis', '')}")

    # 查看暂停状态
    snapshot = graph.get_state(config)
    print(f"下一个待执行节点: {snapshot.next}")

    # 模拟人工审核：修改状态后恢复
    print("\n=== 人工审核：批准 ===")
    graph.update_state(config, {"approved": True})
    result = graph.invoke(None, config)
    print(f"最终输出: {result.get('final_output', '')}")
