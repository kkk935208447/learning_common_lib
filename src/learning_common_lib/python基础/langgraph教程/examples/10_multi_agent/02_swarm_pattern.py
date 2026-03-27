"""
10_multi_agent / 02_swarm_pattern

目标:
    Swarm 模式 — Agent 间点对点协作，通过 handoff 机制传递控制权

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    Command + active_agent 状态

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/10_multi_agent/02_swarm_pattern.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/10_multi_agent/02_swarm_pattern.py

预期现象:
    多个 Agent 通过 Command 互相移交控制权，无中心调度器

生产提醒:
    Swarm 适合 Agent 能力互补且交互模式明确的场景，注意防止循环移交
"""
from __future__ import annotations

import asyncio
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class State(TypedDict, total=False):
    query: str
    active_agent: str
    messages: list[str]
    handoff_count: int
    max_handoffs: int


# ---------------------------------------------------------------------------
# Agent 节点 — 每个 Agent 可通过 Command 移交控制权
# ---------------------------------------------------------------------------

def triage_agent(state: State) -> Command[Literal["sales_agent", "support_agent", "done"]]:
    """分流 Agent：根据查询内容移交给对应 Agent"""
    query = state.get("query", "")
    msgs = state.get("messages", [])
    count = state.get("handoff_count", 0) + 1
    print(f"[Triage] 分析: {query}")

    if "购买" in query or "价格" in query:
        return Command(
            goto="sales_agent",
            update={"active_agent": "sales", "messages": [*msgs, "triage→sales"], "handoff_count": count},
        )
    elif "问题" in query or "故障" in query:
        return Command(
            goto="support_agent",
            update={"active_agent": "support", "messages": [*msgs, "triage→support"], "handoff_count": count},
        )
    return Command(
        goto="done",
        update={"messages": [*msgs, "triage→done（无需转接）"], "handoff_count": count},
    )


def sales_agent(state: State) -> Command[Literal["support_agent", "done"]]:
    """销售 Agent：处理购买相关，可能转接技术支持"""
    query = state.get("query", "")
    msgs = state.get("messages", [])
    count = state.get("handoff_count", 0) + 1
    print(f"[Sales] 处理: {query}")

    if "技术" in query:
        # 涉及技术问题，移交给支持
        return Command(
            goto="support_agent",
            update={"active_agent": "support", "messages": [*msgs, "sales→support（技术问题）"], "handoff_count": count},
        )
    return Command(
        goto="done",
        update={"messages": [*msgs, "sales 处理完成"], "handoff_count": count},
    )


def support_agent(state: State) -> Command[Literal["done"]]:
    """技术支持 Agent：处理技术问题"""
    query = state.get("query", "")
    msgs = state.get("messages", [])
    count = state.get("handoff_count", 0) + 1
    print(f"[Support] 处理: {query}")
    return Command(
        goto="done",
        update={"messages": [*msgs, "support 处理完成"], "handoff_count": count},
    )


def done(state: State) -> dict:
    """结束节点"""
    msgs = state.get("messages", [])
    print(f"[Done] 处理链: {' → '.join(msgs)}")
    return {}


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------

builder = StateGraph(State)
builder.add_node("triage_agent", triage_agent)
builder.add_node("sales_agent", sales_agent)
builder.add_node("support_agent", support_agent)
builder.add_node("done", done)

builder.add_edge(START, "triage_agent")
builder.add_edge("done", END)

graph = builder.compile()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    async def main() -> None:
        queries = [
            "我想购买企业版",
            "我想购买但有技术问题",
            "系统故障无法登录",
            "你好，随便聊聊",
        ]
        for q in queries:
            print(f"\n{'='*50}")
            print(f"查询: {q}")
            result = await graph.ainvoke({"query": q, "messages": [], "handoff_count": 0, "max_handoffs": 5})
            print(f"移交次数: {result.get('handoff_count', 0)}")

    asyncio.run(main())
