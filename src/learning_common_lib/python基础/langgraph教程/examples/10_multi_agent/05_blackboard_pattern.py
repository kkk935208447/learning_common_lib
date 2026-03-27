"""
10_multi_agent / 05_blackboard_pattern

目标:
    黑板模式 — 共享状态协调多 Agent，参考 AgenticRAG "受控角色 + 共享状态" 设计

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    Annotated reducer + 多节点读写同一状态

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/10_multi_agent/05_blackboard_pattern.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/10_multi_agent/05_blackboard_pattern.py

预期现象:
    多个 Agent 读写共享黑板状态，每个 Agent 只修改自己负责的部分

生产提醒:
    黑板模式的核心是状态隔离 — 每个 Agent 只写自己的 key，通过 reducer 合并
"""
from __future__ import annotations

import asyncio
import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph


# ---------------------------------------------------------------------------
# 黑板状态 — 所有 Agent 共享
# ---------------------------------------------------------------------------

class Blackboard(TypedDict, total=False):
    # 输入
    query: str
    # 各 Agent 写入的区域
    research_notes: Annotated[list[str], operator.add]
    code_snippets: Annotated[list[str], operator.add]
    review_comments: Annotated[list[str], operator.add]
    # 控制
    phase: str  # "research" | "code" | "review" | "done"
    iteration: int


# ---------------------------------------------------------------------------
# Agent 节点 — 每个 Agent 只写自己负责的 key
# ---------------------------------------------------------------------------

def research_agent(state: Blackboard) -> dict:
    """研究 Agent：写入 research_notes"""
    query = state.get("query", "")
    existing = state.get("research_notes", [])
    print(f"[Research] 研究 '{query}'，已有 {len(existing)} 条笔记")
    return {
        "research_notes": [f"发现: {query} 相关的 3 个关键概念"],
        "phase": "code",
    }


def code_agent(state: Blackboard) -> dict:
    """编码 Agent：读取 research_notes，写入 code_snippets"""
    notes = state.get("research_notes", [])
    print(f"[Code] 基于 {len(notes)} 条研究笔记编码")
    return {
        "code_snippets": [f"基于研究实现的代码片段 (参考 {len(notes)} 条笔记)"],
        "phase": "review",
    }


def review_agent(state: Blackboard) -> dict:
    """审核 Agent：读取所有内容，写入 review_comments"""
    notes = state.get("research_notes", [])
    code = state.get("code_snippets", [])
    iteration = state.get("iteration", 0) + 1
    print(f"[Review] 审核 {len(notes)} 条笔记 + {len(code)} 段代码, iteration={iteration}")

    # 模拟：第一轮需要修改，第二轮通过
    if iteration < 2:
        return {
            "review_comments": ["需要补充更多细节"],
            "phase": "research",
            "iteration": iteration,
        }
    return {
        "review_comments": ["审核通过"],
        "phase": "done",
        "iteration": iteration,
    }


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

def phase_route(state: Blackboard) -> Literal["research", "code", "review", "__end__"]:
    phase = state.get("phase", "done")
    if phase == "research":
        return "research"
    elif phase == "code":
        return "code"
    elif phase == "review":
        return "review"
    return "__end__"


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------

builder = StateGraph(Blackboard)
builder.add_node("research", research_agent)
builder.add_node("code", code_agent)
builder.add_node("review", review_agent)

builder.add_edge(START, "research")
builder.add_edge("research", "code")
builder.add_edge("code", "review")
builder.add_conditional_edges("review", phase_route)

graph = builder.compile()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    async def main() -> None:
        result = await graph.ainvoke({
            "query": "LangGraph 黑板模式",
            "research_notes": [],
            "code_snippets": [],
            "review_comments": [],
            "phase": "research",
            "iteration": 0,
        })
        print(f"\n黑板最终状态:")
        print(f"  研究笔记: {result.get('research_notes')}")
        print(f"  代码片段: {result.get('code_snippets')}")
        print(f"  审核意见: {result.get('review_comments')}")
        print(f"  迭代次数: {result.get('iteration')}")

    asyncio.run(main())
