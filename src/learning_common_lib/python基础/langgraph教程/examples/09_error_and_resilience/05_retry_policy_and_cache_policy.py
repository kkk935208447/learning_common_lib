from __future__ import annotations

"""
目标：演示 LangGraph 内置 `RetryPolicy` 和 `CachePolicy`。
关键 API：StateGraph.add_node(..., retry_policy=..., cache_policy=...)、InMemoryCache
运行命令：python 05_retry_policy_and_cache_policy.py
预期现象：
  1. 不稳定节点第一次失败，`RetryPolicy` 自动重试后成功
  2. 昂贵节点首次运行后写入缓存，同样输入第二次执行直接命中缓存

生产提醒：
  - `RetryPolicy` 适合处理真正可重试的异常，不要替代业务级 fallback
  - `CachePolicy` 只适合纯函数/幂等节点，避免缓存带副作用的节点
  - 本例用全局计数器打印中间态，方便观察自动重试和缓存命中
"""

import asyncio
from typing import TypedDict

from langgraph.cache.memory import InMemoryCache
from langgraph.graph import END, START, StateGraph
from langgraph.types import CachePolicy, RetryPolicy


ATTEMPTS = {"unstable": 0, "expensive": 0}


class PolicyState(TypedDict, total=False):
    query: str
    unstable_result: str
    expensive_result: str


def unstable_node(state: PolicyState) -> dict:
    ATTEMPTS["unstable"] += 1
    attempt = ATTEMPTS["unstable"]
    print(f"[unstable_node] attempt={attempt} query={state.get('query')}")
    if attempt == 1:
        raise RuntimeError("第一次调用模拟瞬态失败")
    return {"unstable_result": f"unstable-ok-attempt-{attempt}"}


def expensive_node(state: PolicyState) -> dict:
    ATTEMPTS["expensive"] += 1
    count = ATTEMPTS["expensive"]
    print(f"[expensive_node] compute_count={count} query={state.get('query')}")
    return {"expensive_result": f"expensive-result-for-{state.get('query')}-#{count}"}


async def main() -> None:
    graph = StateGraph(PolicyState)
    graph.add_node(
        "unstable",
        unstable_node,
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_interval=0.1,
            jitter=False,
            retry_on=lambda exc: isinstance(exc, RuntimeError),
        ),
    )
    graph.add_node(
        "expensive",
        expensive_node,
        cache_policy=CachePolicy(ttl=60),
    )
    graph.add_edge(START, "unstable")
    graph.add_edge("unstable", "expensive")
    graph.add_edge("expensive", END)
    app = graph.compile(cache=InMemoryCache())

    print("=== 第一次执行：会发生重试，并写入缓存 ===")
    ATTEMPTS["unstable"] = 0
    ATTEMPTS["expensive"] = 0
    result1 = await app.ainvoke({"query": "travel-policy"})
    print(f"result1={result1}\n")

    print("=== 第二次执行：相同输入，昂贵节点命中缓存 ===")
    ATTEMPTS["unstable"] = 0
    result2 = await app.ainvoke({"query": "travel-policy"})
    print(f"result2={result2}\n")

    print("=== 观察结论 ===")
    print(f"unstable attempts={ATTEMPTS['unstable']} (每次调用都可重试)")
    print(f"expensive compute_count={ATTEMPTS['expensive']} (相同输入第二次不应再次计算)")


if __name__ == "__main__":
    asyncio.run(main())
