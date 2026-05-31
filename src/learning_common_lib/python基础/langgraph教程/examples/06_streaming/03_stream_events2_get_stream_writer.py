"""
06_streaming / 03_stream_events2_get_stream_writer

目标：
    彻底讲清 get_stream_writer() —— 在节点内部把"自定义进度事件"注入到
    当前 graph.stream() 这条流里。它和"节点 return 改 state"是两条独立的路。

核心心智模型（一句话）：
    writer({...})            ->  自定义事件，只走 stream_mode="custom"
    return {"field": value}  ->  状态增量，  只走 stream_mode="updates"/"values"
    两者都在【同一个进程】内，从【同一次 astream() 循环】里冒出来，无任何网络/Redis。

关键 API：
    from langgraph.config import get_stream_writer
    writer = get_stream_writer()
    writer(任意可序列化对象)

运行方式：
    uv run python examples/06_streaming/03_stream_events2_get_stream_writer.py

预期现象：
    1. custom 模式：只看到 writer() 推的进度事件，看不到 state
    2. updates 模式：只看到节点 return 的状态增量，看不到进度事件
    3. 组合模式：两者都拿到，且能按来源（mode）区分
    4. 全程单进程，writer 推的对象直接从 astream 的 for 循环里被 yield 出来

生产提醒：
    - get_stream_writer() 是【进程内】机制，生命周期绑定这一次 astream() 调用，
      stream 结束它就失效。它不是 Redis pub/sub，不跨进程。
    - 想把事件送到浏览器：在下面 astream 的【消费端】接 SSE / WebSocket；
      只有"跑图的 worker"和"持有前端长连接的进程"不是同一个时，才需要 Redis 中转。
    - writer 推的对象最终要 json 序列化给前端，所以别塞不可序列化的东西。
"""
from __future__ import annotations

import asyncio
import time
from typing import TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    query: str
    docs: list[str]
    answer: str


# ── 节点 1：检索 ──────────────────────────────────────────────
# 这是一个"耗时"节点：内部有多个子步骤。我们想让前端实时看到进度，
# 但这些进度【不应该】污染 state —— 所以用 writer 推，而不是 return。
def retrieve(state: State) -> dict:
    # 关键：在节点内部任意位置拿到 writer。它从当前运行上下文自动绑定，
    # 不需要你手动传参进来。
    writer = get_stream_writer()

    writer({"node": "retrieve", "status": "start", "label": "开始检索"})

    docs: list[str] = []
    for i in range(3):
        time.sleep(0.3)                      # 模拟一次外部调用 / 子步骤
        docs.append(f"doc_{i}")
        # 这条进度只会从 custom 流冒出来，不进 state
        writer({"node": "retrieve", "status": "progress", "done": i + 1, "total": 3})

    writer({"node": "retrieve", "status": "done", "count": len(docs)})

    # return 改的是 state，走 updates/values —— 与上面的 writer 是两条平行的路
    return {"docs": docs}


# ── 节点 2：生成 ──────────────────────────────────────────────
def generate(state: State) -> dict:
    writer = get_stream_writer()
    writer({"node": "generate", "status": "start",
            "label": f"基于 {len(state['docs'])} 篇文档生成"})
    time.sleep(0.3)
    answer = f"综合 {len(state['docs'])} 篇文档得到的回答"
    writer({"node": "generate", "status": "done"})
    return {"answer": answer}


def build():
    g = StateGraph(State)
    g.add_node("retrieve", retrieve)
    g.add_node("generate", generate)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", END)
    return g.compile()


async def main() -> None:
    app = build()
    inputs = {"query": "什么是 LangGraph 流式输出"}

    # ── 演示 1：只看 custom —— 只拿到 writer() 推的进度事件 ──────────
    print("=== stream_mode='custom'（只有 writer 推的事件）===\n")
    async for chunk in app.astream(inputs, stream_mode="custom"):
        # 单一模式时，chunk 就是 writer() 推进去的那个对象，原样返回
        print(f"  custom -> {chunk}")

    # ── 演示 2：只看 updates —— 只拿到节点 return 的状态增量 ─────────
    print("\n=== stream_mode='updates'（只有 return 的状态增量）===\n")
    async for chunk in app.astream(inputs, stream_mode="updates"):
        # 注意：这里完全看不到上面那些 progress 事件，它们不在 state 里
        print(f"  updates -> {chunk}")

    # ── 演示 3：组合 —— 进度事件 + 状态增量都要，并按来源区分 ─────────
    print("\n=== stream_mode=['custom','updates']（两者都要，按 mode 区分来源）===\n")
    async for mode, chunk in app.astream(inputs, stream_mode=["custom", "updates"]):
        # 传 list 时，每个 chunk 变成 (mode, data) 二元组 —— 这是区分来源的关键
        if mode == "custom":
            print(f"  [进度] {chunk}")
        else:  # "updates"
            print(f"  [状态] {chunk}")

    # ── 演示 4（可选）：这才是"推给前端"那一跳的位置 ──────────────────
    # 真实后端里，你会在下面这个循环体内把 chunk 通过 SSE/WebSocket 发出去。
    # get_stream_writer() 负责"节点 -> 这个循环"，SSE 负责"这个循环 -> 浏览器"。
    print("\n=== 模拟推送给前端（实际可换成 await sse.send(...)）===\n")
    async for mode, chunk in app.astream(inputs, stream_mode=["custom", "updates"]):
        payload = {"mode": mode, "data": chunk}
        # await sse.send(json.dumps(payload, ensure_ascii=False))   # ← 真实场景
        print(f"  would_send -> {payload}")


if __name__ == "__main__":
    asyncio.run(main())