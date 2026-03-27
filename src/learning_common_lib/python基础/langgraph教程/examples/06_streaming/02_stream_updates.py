"""
06_streaming / 02_stream_updates

目标:
    06_streaming / 02_stream_updates

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    见本文件导入、节点函数和构图代码

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/06_streaming/02_stream_updates.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/06_streaming/02_stream_updates.py

预期现象:
    运行后可观察本文件对应的状态推进、输出或集成行为

生产提醒:
    迁移到业务代码前，请结合 README / best_practices / pitfalls 一起阅读
"""
from __future__ import annotations

import asyncio

"""
目标：演示 stream(mode="updates") 模式——每步只输出增量更新
关键 API：graph.stream(inputs, mode="updates")
运行命令：python 02_stream_updates.py
预期现象：
  1. 每个节点执行后只输出该节点产生的增量变化
  2. 输出格式为 {node_name: {field: value}}
  3. 适用于只关心变化字段的场景
生产提醒：
  - updates 模式数据量小，适合带宽受限的场景
  - 前端需要自行维护完整状态（累积增量）
  - 与 values 模式的选择取决于前端架构
"""

from typing import TypedDict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, MessagesState, StateGraph


# ── 1. 使用 MessagesState 演示 ──────────────────────────────
def researcher(state: MessagesState) -> dict:
    """研究节点：搜索信息"""
    return {"messages": [AIMessage(content="[研究] 找到了 3 篇相关文档")]}


def analyzer(state: MessagesState) -> dict:
    """分析节点：分析结果"""
    return {"messages": [AIMessage(content="[分析] 文档主题集中在 Agent 架构")]}


def writer(state: MessagesState) -> dict:
    """撰写节点：生成回复"""
    return {"messages": [AIMessage(content="[撰写] 根据分析结果，LangGraph 的核心是...")]}


# ── 2. 使用自定义 State 演示（更直观看到增量）────────────────
class PipelineState(TypedDict):
    query: str
    search_results: list[str]
    analysis: str
    final_answer: str


def search_node(state: PipelineState) -> dict:
    return {"search_results": [f"结果1: {state['query']}", f"结果2: {state['query']}"]}


def analyze_node(state: PipelineState) -> dict:
    return {"analysis": f"分析了 {len(state.get('search_results', []))} 条结果"}


def answer_node(state: PipelineState) -> dict:
    return {"final_answer": f"最终回答: {state.get('analysis', '')}"}


async def main() -> None:
    # ── MessagesState 版本 ──────────────────────────────────
    print("=== stream(mode='updates') - MessagesState ===\n")
    graph1 = StateGraph(MessagesState)
    graph1.add_node("researcher", researcher)
    graph1.add_node("analyzer", analyzer)
    graph1.add_node("writer", writer)
    graph1.set_entry_point("researcher")
    graph1.add_edge("researcher", "analyzer")
    graph1.add_edge("analyzer", "writer")
    graph1.add_edge("writer", END)
    app1 = graph1.compile()

    async for update in app1.astream(
        {"messages": [HumanMessage(content="介绍 LangGraph")]},
        stream_mode="updates",
    ):
        # update 格式: {node_name: {field: value}}
        for node_name, node_output in update.items():
            new_msgs = node_output.get("messages", [])
            print(f"  节点 [{node_name}] 产生 {len(new_msgs)} 条新消息:")
            for msg in new_msgs:
                print(f"    -> {msg.content}")

    # ── 自定义 State 版本（更直观）──────────────────────────
    print("\n=== stream(mode='updates') - 自定义 State ===\n")
    graph2 = StateGraph(PipelineState)
    graph2.add_node("search", search_node)
    graph2.add_node("analyze", analyze_node)
    graph2.add_node("answer", answer_node)
    graph2.set_entry_point("search")
    graph2.add_edge("search", "analyze")
    graph2.add_edge("analyze", "answer")
    graph2.add_edge("answer", END)
    app2 = graph2.compile()

    async for update in app2.astream(
        {"query": "LangGraph 流式输出"},
        stream_mode="updates",
    ):
        for node_name, delta in update.items():
            print(f"  节点 [{node_name}] 增量更新:")
            for key, value in delta.items():
                print(f"    {key} = {value}")

    print("\n提示: updates 模式只传输变化的字段，适合带宽敏感场景")


if __name__ == "__main__":
    asyncio.run(main())
