from __future__ import annotations

"""
目标: 两层 Agent — 全局调度 + 子任务执行，参考 AgenticRAG GlobalGraph + SubtaskGraph 双图
关键 API: StateGraph 嵌套、子图独立编译
运行命令: python 04_hierarchical_agents.py
预期现象: 全局调度器分解任务 → 子任务 Agent 独立执行 → 结果汇总到全局
生产提醒: 层级 Agent 适合任务可分解的场景，注意子任务间的依赖关系
"""

import asyncio
import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class SubAgentState(TypedDict, total=False):
    task: str
    agent_type: str  # "researcher" | "writer" | "reviewer"
    result: str


class GlobalState(TypedDict, total=False):
    query: str
    subtasks: list[dict]
    results: Annotated[list[str], operator.add]
    iteration: int
    status: str


# ---------------------------------------------------------------------------
# 子任务 Agent 图
# ---------------------------------------------------------------------------

def sub_execute(state: SubAgentState) -> dict:
    """子 Agent 执行"""
    agent = state.get("agent_type", "unknown")
    task = state.get("task", "")
    print(f"  [{agent}] 执行: {task}")
    return {"result": f"{agent} 完成: {task}"}


sub_builder = StateGraph(SubAgentState)
sub_builder.add_node("execute", sub_execute)
sub_builder.add_edge(START, "execute")
sub_builder.add_edge("execute", END)
sub_agent_graph = sub_builder.compile()


# ---------------------------------------------------------------------------
# 全局调度节点
# ---------------------------------------------------------------------------

def decompose(state: GlobalState) -> dict:
    """分解任务"""
    query = state.get("query", "")
    iteration = state.get("iteration", 0) + 1
    print(f"\n[全局调度] 第 {iteration} 轮, query='{query}'")
    subtasks = [
        {"task": f"研究 {query} 的背景", "agent_type": "researcher"},
        {"task": f"撰写 {query} 的报告", "agent_type": "writer"},
        {"task": f"审核 {query} 的质量", "agent_type": "reviewer"},
    ]
    return {"subtasks": subtasks, "iteration": iteration}


async def dispatch(state: GlobalState) -> dict:
    """分发子任务到子 Agent"""
    subtasks = state.get("subtasks", [])
    results: list[str] = []
    for st in subtasks:
        sub_result = await sub_agent_graph.ainvoke(st)
        results.append(sub_result.get("result", ""))
    return {"results": results}


def aggregate(state: GlobalState) -> dict:
    """汇总结果"""
    results = state.get("results", [])
    print(f"[汇总] 收到 {len(results)} 个子任务结果")
    return {"status": "completed"}


# ---------------------------------------------------------------------------
# 构建全局图
# ---------------------------------------------------------------------------

builder = StateGraph(GlobalState)
builder.add_node("decompose", decompose)
builder.add_node("dispatch", dispatch)
builder.add_node("aggregate", aggregate)

builder.add_edge(START, "decompose")
builder.add_edge("decompose", "dispatch")
builder.add_edge("dispatch", "aggregate")
builder.add_edge("aggregate", END)

graph = builder.compile()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    async def main() -> None:
        result = await graph.ainvoke({
            "query": "LangGraph 层级 Agent 架构",
            "results": [],
            "iteration": 0,
        })
        print(f"\n状态: {result.get('status')}")
        print(f"结果:")
        for r in result.get("results", []):
            print(f"  - {r}")

    asyncio.run(main())
