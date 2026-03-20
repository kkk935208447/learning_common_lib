"""函数式 vs Graph API 对比

目标：
    用同一个工作流（文本处理管道）分别用 Functional API 和 Graph API 实现，
    对比两种风格的代码结构、适用场景和取舍。

关键 API：
    - Functional: @entrypoint + @task
    - Graph: StateGraph + add_node + add_edge

运行命令：
    python 03_functional_vs_graph.py

预期现象：
    两种实现产生相同的输出结果，但代码风格截然不同。

生产提醒：
    - 简单线性/分支流程 → Functional API（代码更简洁）
    - 复杂拓扑（循环、并行、子图）→ Graph API（更灵活）
    - 两种 API 可以混用：Graph 节点内部调用 @task
"""
from __future__ import annotations

import asyncio
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.func import entrypoint, task
from langgraph.graph import END, StateGraph


# ══════════════════════════════════════════════════════════
# 方案 A：Functional API 实现
# ══════════════════════════════════════════════════════════

@task
def func_clean(text: str) -> str:
    """清洗文本"""
    cleaned = text.strip().lower()
    print(f"  [Functional:clean] '{text}' -> '{cleaned}'")
    return cleaned


@task
def func_tokenize(text: str) -> list[str]:
    """分词"""
    tokens = text.split()
    print(f"  [Functional:tokenize] {len(tokens)} 个词")
    return tokens


@task
def func_count(tokens: list[str]) -> dict[str, int]:
    """词频统计"""
    freq: dict[str, int] = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    print(f"  [Functional:count] {len(freq)} 个唯一词")
    return freq


func_checkpointer = MemorySaver()


@entrypoint(checkpointer=func_checkpointer)
def functional_pipeline(text: str) -> dict[str, int]:
    """Functional API：原生 Python 控制流"""
    cleaned = func_clean(text).result()
    tokens = func_tokenize(cleaned).result()
    freq = func_count(tokens).result()
    return freq


# ══════════════════════════════════════════════════════════
# 方案 B：Graph API 实现
# ══════════════════════════════════════════════════════════

class PipelineState(TypedDict):
    text: str
    cleaned: str
    tokens: list[str]
    freq: dict[str, int]


def graph_clean(state: PipelineState) -> dict:
    cleaned = state["text"].strip().lower()
    print(f"  [Graph:clean] '{state['text']}' -> '{cleaned}'")
    return {"cleaned": cleaned}


def graph_tokenize(state: PipelineState) -> dict:
    tokens = state["cleaned"].split()
    print(f"  [Graph:tokenize] {len(tokens)} 个词")
    return {"tokens": tokens}


def graph_count(state: PipelineState) -> dict:
    freq: dict[str, int] = {}
    for t in state["tokens"]:
        freq[t] = freq.get(t, 0) + 1
    print(f"  [Graph:count] {len(freq)} 个唯一词")
    return {"freq": freq}


def build_graph_pipeline():
    graph = StateGraph(PipelineState)
    graph.add_node("clean", graph_clean)
    graph.add_node("tokenize", graph_tokenize)
    graph.add_node("count", graph_count)
    graph.set_entry_point("clean")
    graph.add_edge("clean", "tokenize")
    graph.add_edge("tokenize", "count")
    graph.add_edge("count", END)
    return graph.compile(checkpointer=MemorySaver())


# ══════════════════════════════════════════════════════════
# 对比总结
# ══════════════════════════════════════════════════════════
COMPARISON = """
┌──────────────┬─────────────────────┬─────────────────────┐
│              │ Functional API      │ Graph API           │
├──────────────┼─────────────────────┼─────────────────────┤
│ 定义方式     │ @entrypoint + @task │ StateGraph + nodes  │
│ 控制流       │ 原生 if/for/while   │ edges + conditions  │
│ 状态管理     │ 函数参数/返回值     │ TypedDict State     │
│ 并行支持     │ 有限                │ Send API 原生支持   │
│ 子图组合     │ 不支持              │ 原生支持            │
│ 可视化       │ 不支持 Mermaid      │ draw_mermaid        │
│ 适用场景     │ 简单线性/分支流程   │ 复杂拓扑/循环/并行  │
│ 代码量       │ 较少                │ 较多                │
│ 学习曲线     │ 低（纯 Python）     │ 中（需理解图概念）  │
└──────────────┴─────────────────────┴─────────────────────┘
"""


if __name__ == "__main__":
    async def main() -> None:
        test_text = "  Hello World hello LangGraph world  "

        print("=== 方案 A: Functional API ===\n")
        config_f = {"configurable": {"thread_id": "func-1"}}
        result_f = await functional_pipeline.ainvoke(test_text, config=config_f)
        print(f"  结果: {result_f}\n")

        print("=== 方案 B: Graph API ===\n")
        graph_app = build_graph_pipeline()
        config_g = {"configurable": {"thread_id": "graph-1"}}
        result_g = await graph_app.ainvoke(
            {"text": test_text, "cleaned": "", "tokens": [], "freq": {}},
            config=config_g,
        )
        print(f"  结果: {result_g['freq']}\n")

        print(COMPARISON)
        print("建议：简单流程用 Functional，复杂拓扑用 Graph，两者可混用。")

    asyncio.run(main())
