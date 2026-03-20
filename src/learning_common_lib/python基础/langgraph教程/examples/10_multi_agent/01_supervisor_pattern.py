from __future__ import annotations

"""
目标: Supervisor 模式 — 中心化调度器分配任务给 Worker
关键 API: 条件边路由 + FakeListChatModel 模拟 LLM 决策
运行命令: python 01_supervisor_pattern.py
预期现象: Supervisor 根据查询类型将任务分配给不同 Worker，Worker 执行后返回结果
生产提醒: Supervisor 是单控制平面原则的体现，所有决策由一个节点统一管理
"""

import asyncio
from typing import Literal, TypedDict

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.graph import END, START, StateGraph

# ---------------------------------------------------------------------------
# LLM — 使用 FakeListChatModel 模拟
# 生产环境替换: from langchain_openai import ChatOpenAI; llm = ChatOpenAI(model="gpt-4o")
# ---------------------------------------------------------------------------

llm = FakeListChatModel(responses=["researcher", "coder", "FINISH"])


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class State(TypedDict, total=False):
    query: str
    messages: list[str]
    next_worker: str
    results: list[str]
    iteration: int


# ---------------------------------------------------------------------------
# Supervisor 节点
# ---------------------------------------------------------------------------

def supervisor(state: State) -> dict:
    """Supervisor：决定下一个 Worker 或结束"""
    query = state.get("query", "")
    iteration = state.get("iteration", 0)
    if iteration >= 2:
        next_w = "FINISH"
    else:
        candidate = llm.invoke(f"为任务选择 worker: {query}").content.strip()
        next_w = candidate if candidate in {"researcher", "coder"} else "FINISH"

    print(f"[Supervisor] iteration={iteration}, 分配给: {next_w}")
    return {"next_worker": next_w, "iteration": iteration + 1}


def route_worker(state: State) -> Literal["researcher", "coder", "__end__"]:
    """路由到对应 Worker"""
    nw = state.get("next_worker", "FINISH")
    if nw == "FINISH":
        return "__end__"
    return nw


# ---------------------------------------------------------------------------
# Worker 节点
# ---------------------------------------------------------------------------

def researcher(state: State) -> dict:
    """研究员 Worker"""
    query = state.get("query", "")
    print(f"[Researcher] 研究: {query}")
    result = f"研究结果: 关于 '{query}' 的 3 篇相关论文"
    return {"results": [*state.get("results", []), result]}


def coder(state: State) -> dict:
    """程序员 Worker"""
    query = state.get("query", "")
    print(f"[Coder] 编码: {query}")
    result = f"代码实现: {query} 的原型代码"
    return {"results": [*state.get("results", []), result]}


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------

builder = StateGraph(State)
builder.add_node("supervisor", supervisor)
builder.add_node("researcher", researcher)
builder.add_node("coder", coder)

builder.add_edge(START, "supervisor")
builder.add_conditional_edges("supervisor", route_worker)
# Worker 完成后回到 Supervisor
builder.add_edge("researcher", "supervisor")
builder.add_edge("coder", "supervisor")

graph = builder.compile()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    async def main() -> None:
        result = await graph.ainvoke({"query": "实现一个 RAG 系统", "results": [], "iteration": 0})
        print(f"\n最终结果:")
        for r in result.get("results", []):
            print(f"  - {r}")

    asyncio.run(main())
