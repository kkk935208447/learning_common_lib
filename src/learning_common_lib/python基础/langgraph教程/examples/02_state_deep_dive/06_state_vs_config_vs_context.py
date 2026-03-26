from __future__ import annotations

"""
目标：讲清 state / config / runtime context 的边界。
关键 API：节点签名中的 RunnableConfig
运行命令：python 06_state_vs_config_vs_context.py
预期现象：
  1. 业务字段进入 state
  2. thread_id / tenant_id / trace_id 进入 config
  3. 外部依赖和凭证不进入 state
生产提醒：
  - 不要把 thread_id / trace_id / tenant_id 当普通业务字段塞进 state
  - state 用来描述“当前任务进展”，config 用来携带“本次运行上下文”
"""

import asyncio
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph


class SearchState(TypedDict, total=False):
    query: str
    normalized_query: str
    result_summary: str


def normalize_query(state: SearchState, config: RunnableConfig) -> dict:
    configurable = config.get("configurable", {})
    tenant_id = configurable.get("tenant_id", "unknown")
    thread_id = configurable.get("thread_id", "unknown")
    trace_id = configurable.get("trace_id", "unknown")
    query = state.get("query", "")

    print("[normalize]")
    print(f"  state.query={query}")
    print(f"  config.thread_id={thread_id}")
    print(f"  config.tenant_id={tenant_id}")
    print(f"  config.trace_id={trace_id}")

    normalized = query.strip().lower()
    return {"normalized_query": normalized}


def execute_search(state: SearchState, config: RunnableConfig) -> dict:
    configurable = config.get("configurable", {})
    api_base = configurable.get("api_base", "https://internal.example")
    normalized = state.get("normalized_query", "")

    print("[search]")
    print(f"  使用外部依赖 api_base={api_base}")
    print("  注意：api_base 属于运行时上下文，不应该写进 state")
    return {"result_summary": f"搜索完成：'{normalized}' 命中 3 条结果"}


async def main() -> None:
    graph = StateGraph(SearchState)
    graph.add_node("normalize", normalize_query)
    graph.add_node("search", execute_search)
    graph.add_edge(START, "normalize")
    graph.add_edge("normalize", "search")
    graph.add_edge("search", END)
    app = graph.compile()

    result = await app.ainvoke(
        {"query": "  最近 30 天 差旅 规则 变化  "},
        config={
            "configurable": {
                "thread_id": "tenant:acme:task:42",
                "tenant_id": "acme",
                "trace_id": "trace-001",
                "api_base": "https://search.internal",
            }
        },
    )
    print("\n最终 state:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
