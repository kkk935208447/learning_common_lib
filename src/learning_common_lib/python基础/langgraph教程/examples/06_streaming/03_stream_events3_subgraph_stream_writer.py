"""
06_streaming / 03_stream_events3_subgraph_stream_writer.py

目标：
    把 get_stream_writer() 和【子图】结合起来，讲清子图事件如何冒到父图 stream。

═══════════════════════════════════════════════════════════════════════
重要更正（基于实测）
    本文件早期版本曾断言：".invoke() 调子图是黑盒，子图内部 get_stream_writer()
    事件进不了父图流"。该说法【错误】，已被实测推翻。

    真实机制：get_stream_writer() 依赖 contextvar 传播。子图调用（无论 .invoke()
    还是 .ainvoke()）只要跑在父图的同一 contextvar 上下文里，子图内部的 writer
    事件就会冒到父图流，并被 subgraphs=True 打上 namespace。

    实测环境：Python 3.11.13 + LangGraph 1.x（2026-05）
    实测结论：
      - 同步父节点es + 子图 .invoke()        → 子图事件正常冒出，带 nampace ✅
      - async 父节点 + 子图 .ainvoke()     → 子图事件正常冒出，带 namespace ✅

═══════════════════════════════════════════════════════════════════════

两条硬规则（先记住）：
  1. 节点同步/异步必须匹配调用方式：
       - 同步节点(def)        → .invoke() / .stream()
       - 纯 async 节点(async) → .ainvoke() / .astream()
  2. get_stream_writer() 的 contextvar 传播：
       - Python >= 3.11：async 任务支持 context 复制，传播正常
       - 手动切断上下文（asyncio.create_task / 起线程 / callbacks=None）会中断传播

关键 API：
    from langgraph.config import get_stream_writer
    parent.astream(inputs, stream_mode=["custom","updates"], subgraphs=True)
    # subgraphs=True + 多 stream_mode 时，每个 chunk 解包为 (namespace, mode, data)
    # namespace: () 表示父图根；("节点名:task_id",) 表示该节点下的子图

运行方式：
    uv run python examples/06_streaming/03_stream_events3_subgraph_stream_writer.py

预期现象（Python 3.11+）：
    - 情况 A（同步节点 + .invoke）：子图 progress 正常冒出，namespace ('A:...')
    - 情况 B（同步节点 + astream 转发）：子图 progress 正常冒出，且可在转发时改写
    - 情况 C（显式 writer 参数）：不依赖 contextvar，跨 Python 版本最稳
"""
from __future__ import annotations

import asyncio
import time
from typing import TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter   # 显式 writer 参数写法用到


# ══════════════════════════════════════════════════════════════
# 1. 子图：节点是【同步 def】，因此既能 .invoke() 也能 .stream()
#    （若改成 async def，则只能 .ainvoke()/.astream()，见 06_streaming/03_stream_events4_subgraph_stream_writer_async.py 文件）
# ══════════════════════════════════════════════════════════════
class SubState(TypedDict):
    q: str
    docs: list[str]


def sub_fetch(state: SubState) -> dict:
    writer = get_stream_writer()          # 子图节点内部也能拿到父图的 writer
    docs: list[str] = []
    for i in range(3):
        time.sleep(0.2)                   # 模拟耗时子步骤
        docs.append(f"doc_{i}")
        # 这条 progress 会冒到父图流（contextvar 传播），带 namespace
        writer({"from": "subgraph", "node": "sub_fetch",
                "status": "progress", "done": i + 1, "total": 3})
    return {"docs": docs}


def build_subgraph():
    g = StateGraph(SubState)
    g.add_node("sub_fetch", sub_fetch)
    g.add_edge(START, "sub_fetch")
    g.add_edge("sub_fetch", END)
    return g.compile()


SUBGRAPH = build_subgraph()


# ══════════════════════════════════════════════════════════════
# 2. 父图状态
# ══════════════════════════════════════════════════════════════
class ParentState(TypedDict):
    query: str
    docs_a: list[str]
    docs_b: list[str]
    docs_c: list[str]


# ── 情况 A：同步节点 + 子图 .invoke() ───────────────────────────
# 实测：子图内部 sub_fetch 的 3 条 progress 会【正常冒到父图流】，
# 带 namespace ('A:<task_id>',)。无需任何手动转发或补发。
# 这是最省事且有效的写法（前提：子图节点是同步的，可被 .invoke 调用）。
def node_a_invoke(state: ParentState) -> dict:
    writer = get_stream_writer()
    writer({"from": "parent", "node": "A", "status": "start",
            "label": "A: 同步节点 + 子图 .invoke()（事件自动带 namespace 冒上来）"})
    result = SUBGRAPH.invoke({"q": state["query"]})   # 事件靠 contextvar 自动传播
    writer({"from": "parent", "node": "A", "status": "done"})
    return {"docs_a": result["docs"]}


# ── 情况 B：同步节点 + astream 转发（需要"改写/过滤"子图事件时用）──
# 当你不满足于"原样冒出"，而是想在父节点里对子图事件做加工
# （改写、过滤、补充上下文、做 schema 翻译）时，用 astream 主动消费子图流再转发。
# 代价是多写几行；好处是完全掌控透传出去的内容。
def node_b_relay(state: ParentState) -> dict:
    writer = get_stream_writer()
    writer({"from": "parent", "node": "B", "status": "start",
            "label": "B: 同步节点 + astream 转发（可改写/过滤子图事件）"})

    docs: list[str] = []
    for ns, mode, chunk in SUBGRAPH.stream(
        {"q": state["query"]},
        stream_mode=["custom", "updates"],
        subgraphs=True,
    ):
        if mode == "custom":
            writer({"relayed_from_ns": ns, "via": "B", **chunk})   # 转发时加标记
        elif mode == "updates":
            for _node, delta in chunk.items():
                docs = delta.get("docs", docs)

    writer({"from": "parent", "node": "B", "status": "done"})
    return {"docs_b": docs}


# ── 情况 C：显式 writer 参数（兜底，不依赖 contextvar）──────────
# 在节点签名里声明 writer: StreamWriter，LangGraph 会自动注入。
# 这种写法在 Python < 3.11 的 async 场景下也能工作，是跨版本最稳的兜底。
def node_c_explicit_writer(state: ParentState, writer: StreamWriter) -> dict:
    writer({"from": "parent", "node": "C", "status": "start",
            "label": "C: 显式 writer 参数（跨 Python 版本最稳的兜底写法）"})
    result = SUBGRAPH.invoke({"q": state["query"]})
    writer({"from": "parent", "node": "C", "status": "done"})
    return {"docs_c": result["docs"]}


def build_parent():
    g = StateGraph(ParentState)
    g.add_node("A", node_a_invoke)
    g.add_node("B", node_b_relay)
    g.add_node("C", node_c_explicit_writer)
    g.add_edge(START, "A")
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    g.add_edge("C", END)
    return g.compile()


# ══════════════════════════════════════════════════════════════
# 3. 消费：父图开 subgraphs=True，观察三种写法的事件
# ══════════════════════════════════════════════════════════════
async def main() -> None:
    app = build_parent()
    inputs = {"query": "LangGraph 子图流式"}

    print("=== 父图 astream(subgraphs=True, mode=['custom','updates']) ===\n")
    async for ns, mode, chunk in app.astream(
        inputs,
        stream_mode=["custom", "updates"],
        subgraphs=True,
    ):
        # subgraphs=True + 多 mode 时，chunk 解包为 (namespace, mode, data)
        ns_label = "根" if ns == () else f"子图{ns}"
        tag = "进度" if mode == "custom" else "状态"
        print(f"  [{ns_label}][{tag}] {chunk}")

    print("""
观察要点（实测，Python 3.11+ / LangGraph 1.x）：
  情况 A：同步节点 + .invoke()，子图 progress【自动】带 namespace 冒出，无需手动转发。
  情况 B：astream 转发，适合需要【改写/过滤】子图事件的场景（注意 relayed_from_ns 标记）。
  情况 C：显式 writer 参数，不依赖 contextvar，跨版本最稳，async 节点首选。

  什么时候才会"传不过来"（真正的黑盒）：
    - Python < 3.11 且用 async 节点（get_stream_writer 失效）
    - 手动切断上下文：asyncio.create_task / 起线程 / callbacks=None
    - 跨进程执行子图（此时才需要 Redis/消息总线）
""")


if __name__ == "__main__":
    asyncio.run(main())