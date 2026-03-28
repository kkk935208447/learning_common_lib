"""
02_state_deep_dive / 06_state_vs_config_vs_context

目标:
    讲清 state / config / runtime context 的边界，并展示这版 LangGraph 里
    `context_schema + runtime.context` 的真实用法。

关键概念:
    - state: 业务进展、可被节点更新、可进入 checkpoint
    - config: 本次调用配置，如 thread_id / trace_id / tags / recursion_limit
    - runtime context: 只读运行时上下文，如 tenant/user/api_base/auth_scope，runtime context 不应混入业务 state，也不应滥塞进 configurable

关键 API:
    - StateGraph(..., context_schema=...)
    - 节点签名中的 RunnableConfig
    - 节点签名中的 Runtime[ContextSchema]

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/02_state_deep_dive/06_state_vs_config_vs_context.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/02_state_deep_dive/06_state_vs_config_vs_context.py

预期现象:
    1. 业务字段进入 state
    2. thread_id / trace_id 进入 config
    3. tenant_id / user_id / api_base / auth_scope 进入 runtime context
    4. 最终打印时可直接看出三者分别承担什么职责

生产提醒:
    - 不要把 thread_id / trace_id / tenant_id 当普通业务字段塞进 state
    - config 更适合“本次调用配置”，runtime context 更适合“本次运行环境/依赖/身份”
    - runtime context 默认应视为只读，不要在节点里把它当成 state 去更新
"""
from __future__ import annotations

import asyncio
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.runtime import Runtime
from langgraph.graph import END, START, StateGraph


class SearchState(TypedDict, total=False):
    """会进入图状态和 checkpoint 的业务字段。

    生产里典型放这里的内容：
    - 经过清洗/改写后的业务输入
    - 当前步骤产出的业务中间结果
    - 最终可审计、可恢复的业务摘要
    """

    query: str
    normalized_query: str
    result_summary: str
    retrieval_plan: str


class SearchContext(TypedDict, total=False):
    """运行时上下文：只读的环境/身份/依赖信息。

    生产里典型放这里的内容：
    - tenant_id / user_id
    - api_base / auth_scope
    - feature_flags
    - 已初始化好的 client / service handle（本例用简单字段代替）
    """

    tenant_id: str
    user_id: str
    api_base: str
    auth_scope: str
    feature_flags: list[str]


def print_boundary_summary(
    *,
    state: SearchState,
    config: RunnableConfig,
    runtime: Runtime[SearchContext],
    stage: str,
) -> None:
    """统一打印 state / config / runtime context 的职责边界。"""
    configurable = config.get("configurable", {})
    runtime_context = runtime.context or {}
    print(f"[{stage}]")
    print("  state      -> 会被节点更新，也可能进入 checkpoint")   # 当 thread id 相同时，state 会从 checkpoint 中恢复
    print(f"    query={state.get('query')!r}")
    print(f"    normalized_query={state.get('normalized_query')!r}")
    print(f"    retrieval_plan={state.get('retrieval_plan')!r}")
    print("  config     -> 本次调用配置，只读取你自己定义的 configurable 键")   # config 的值并不会进入 checkpoint
    print(f"    thread_id={configurable.get('thread_id', 'unknown')}")
    print(f"    trace_id={configurable.get('trace_id', 'unknown')}")
    print(f"    idempotency_key={configurable.get('idempotency_key', 'unknown')}")
    print("  context    -> 本次运行环境/身份/依赖，默认应视为只读")              # context 上下文的依赖也不会进入 checkpoint
    print(f"    tenant_id={runtime_context.get('tenant_id', 'unknown')}")
    print(f"    user_id={runtime_context.get('user_id', 'unknown')}")
    print(f"    api_base={runtime_context.get('api_base', 'unknown')}")
    print(f"    auth_scope={runtime_context.get('auth_scope', 'unknown')}")
    print(f"    feature_flags={runtime_context.get('feature_flags', [])}")


def normalize_query(
    state: SearchState,
    config: RunnableConfig,
    runtime: Runtime[SearchContext],
) -> dict:
    query = state.get("query", "")
    print_boundary_summary(state=state, config=config, runtime=runtime, stage="normalize")

    normalized = query.strip().lower()
    retrieval_plan = f"plan://search/{normalized.replace(' ', '-')}"
    print("  说明：normalize 节点只把业务产物写回 state，不把 tenant/api_base 写回 state")
    return {
        "normalized_query": normalized,
        "retrieval_plan": retrieval_plan,
    }


def execute_search(
    state: SearchState,
    config: RunnableConfig,
    runtime: Runtime[SearchContext],
) -> dict:
    configurable = config.get("configurable", {})
    runtime_context = runtime.context or {}
    api_base = runtime_context.get("api_base", "https://internal.example")
    auth_scope = runtime_context.get("auth_scope", "read")
    feature_flags = runtime_context.get("feature_flags", [])
    trace_id = configurable.get("trace_id", "unknown")
    normalized = state.get("normalized_query", "")
    retrieval_plan = state.get("retrieval_plan", "unknown")

    print("[search]")
    print(f"  state.normalized_query={normalized}")
    print(f"  state.retrieval_plan={retrieval_plan}")
    print(f"  config.trace_id={trace_id}")
    print(f"  context.api_base={api_base}")
    print(f"  context.auth_scope={auth_scope}")
    print(f"  context.feature_flags={feature_flags}")
    print("  说明：api_base/auth_scope/feature_flags 属于运行时上下文，不应该写进 state")
    return {
        "result_summary": (
            f"搜索完成：'{normalized}' 命中 3 条结果 "
            f"(scope={auth_scope}, api_base={api_base}, flags={feature_flags})"
        )
    }


async def main() -> None:
    graph = StateGraph(SearchState, context_schema=SearchContext)
    graph.add_node("normalize", normalize_query)
    graph.add_node("search", execute_search)
    graph.add_edge(START, "normalize")
    graph.add_edge("normalize", "search")
    graph.add_edge("search", END)
    app = graph.compile(checkpointer=MemorySaver())

    thread_id = "tenant:acme:task:42"

    print("=== 场景 1：第一次运行 ===")
    result = await app.ainvoke(
        {"query": "  最近 30 天 差旅 规则 变化  "},
        config={
            "configurable": {
                "thread_id": thread_id,
                "trace_id": "trace-001",
                "idempotency_key": "idem-001",
            }
        },
        context={
            "tenant_id": "acme",
            "user_id": "u-001",
            "api_base": "https://search.internal",
            "auth_scope": "travel_rule.read",
            "feature_flags": ["use-es", "trace-search"],
        },
    )
    print("\n第一次运行后的最终 state:")
    print(result)
    snapshot1 = await app.aget_state({"configurable": {"thread_id": thread_id}})  # 获得 thread_id 对应的快照，.values 是 state 的值
    print("第一次运行后的 checkpoint state:")
    print(snapshot1.values)

    print("\n=== 场景 2：同一 thread 再运行一次，但换掉 config/context ===")
    result2 = await app.ainvoke(
        {"query": "  最近 90 天 差旅 规则 变化  "},
        config={
            "configurable": {
                "thread_id": thread_id,
                "trace_id": "trace-002",
                "idempotency_key": "idem-002",
            }
        },
        context={
            "tenant_id": "acme",
            "user_id": "u-001",
            "api_base": "https://search.backup.internal",
            "auth_scope": "travel_rule.read",
            "feature_flags": ["fallback-index"],
        },
    )
    print("\n第二次运行后的最终 state:")
    print(result2)
    snapshot2 = await app.aget_state({"configurable": {"thread_id": thread_id}})  # 获得 thread_id 对应的快照，.values 是 state 的值
    print("第二次运行后的 checkpoint state:")
    print(snapshot2.values)

    print("\n结论:")
    print("  - state: query / normalized_query / retrieval_plan / result_summary")
    print("           这些字段会成为业务状态，也可能进入 checkpoint")
    print("  - config: thread_id / trace_id / idempotency_key")
    print("           它们描述的是“本次调用配置”，不会自动变成业务 state")
    print("  - runtime context: tenant_id / user_id / api_base / auth_scope / feature_flags")
    print("           它们描述的是“本次运行环境/身份/依赖”，默认应视为只读")
    print("  - 实战中通常是：")
    print("      state   负责业务推进")
    print("      config  负责调用与追踪")
    print("      context 负责环境、身份、权限、依赖注入")


if __name__ == "__main__":
    asyncio.run(main())
