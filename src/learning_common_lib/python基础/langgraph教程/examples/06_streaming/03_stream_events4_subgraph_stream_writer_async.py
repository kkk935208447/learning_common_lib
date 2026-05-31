"""
06_streaming / 05_subgraph_stream_writer_async

目标：
    全 async 节点版本，验证 async 路径下 get_stream_writer() 穿透子图调用的行为。
    与同步版本（03_stream_events3 / 同步节点 + .invoke()）配套阅读。

═══════════════════════════════════════════════════════════════════════
实测确认（已在本机跑通）
    实测环境：Python 3.11.13 + LangGraph 1.x（2026-05，请用 pip show langgraph 核对版本号）
    实测结论：
      - A（async 节点 + 子图 .ainvoke()）：子图 progress 正常冒出，namespace ('A:...') ✅
      - B（async 节点 + 子图 .ainvoke()）：第二个 async 节点，同样正常冒出 ('B:...') ✅
      - C（父节点用显式 writer 参数）    ：同样正常冒出 ('C:...') ✅
    => 3.11+ 下，async 节点 + .ainvoke() 时 contextvar 正常传播，子图 writer 事件
       自动冒到父图流。这是生产用 async 编排的基线行为。
═══════════════════════════════════════════════════════════════════════

两条硬规则（先记住）：
  1. 节点同步/异步必须匹配调用方式：
       - 纯 async 子图（节点 async def）→ 只能 .ainvoke()/.astream()
       - 用 .invoke() 调纯 async 子图 → 直接 TypeError: No synchronous function provided
         （在执行层就失败，跟流式传播无关）。想用 .invoke() 就得给子图节点同步实现。
  2. get_stream_writer() 的 contextvar 传播：
       - Python >= 3.11：async 任务支持 context 复制，传播正常（本文件实测）
       - 手动切断上下文（asyncio.create_task / 起线程 / callbacks=None）会中断传播

运行方式：
    uv run python examples/06_streaming/05_subgraph_stream_writer_async.py
"""
from __future__ import annotations

import asyncio
import sys
from typing import TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter   # 用于显式 writer 参数的类型


# ══════════════════════════════════════════════════════════════
# 子图：节点是 async def，因此只能 .ainvoke()/.astream() 调用
# ══════════════════════════════════════════════════════════════
class SubState(TypedDict):
    q: str
    docs: list[str]


async def sub_fetch(state: SubState) -> dict:
    writer = get_stream_writer()          # async 节点里取 writer（3.11+ 才稳，实测正常）
    docs: list[str] = []
    for i in range(3):
        await asyncio.sleep(0.2)          # async 等待
        docs.append(f"doc_{i}")
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
# 父图
# ══════════════════════════════════════════════════════════════
class ParentState(TypedDict):
    query: str
    docs_a: list[str]
    docs_b: list[str]
    docs_c: list[str]


# ── A：async 节点 + 子图 .ainvoke() ────────────────────────────
# 实测：子图 progress 自动带 namespace ('A:...') 冒出，无需传 config、无需手动转发。
async def node_a_ainvoke(state: ParentState) -> dict:
    writer = get_stream_writer()
    writer({"from": "parent", "node": "A", "status": "start",
            "label": "A: async 节点 + 子图 .ainvoke()"})
    result = await SUBGRAPH.ainvoke({"q": state["query"]})
    writer({"from": "parent", "node": "A", "status": "done"})
    return {"docs_a": result["docs"]}


# ── B：async 节点 + 子图 .ainvoke()（第二个，验证可复现）─────────
# 注意函数名：用的是 .ainvoke()。纯 async 子图不能用 .invoke()，
# 否则报 TypeError: No synchronous function provided（见顶部硬规则1）。
async def node_b_ainvoke(state: ParentState) -> dict:
    writer = get_stream_writer()
    writer({"from": "parent", "node": "B", "status": "start",
            "label": "B: async 节点 + 子图 .ainvoke()（纯 async 子图只能异步调）"})
    result = await SUBGRAPH.ainvoke({"q": state["query"]})
    writer({"from": "parent", "node": "B", "status": "done"})
    return {"docs_b": result["docs"]}


# ── C：父节点用【显式 writer 参数】──────────────────────────────
# 在节点签名里声明 writer: StreamWriter，LangGraph 会自动注入，不依赖
# get_stream_writer()/contextvar。这让【父节点本身】在 Python < 3.11 的
# async 场景下也能稳定拿到 writer。
#
# 但要注意一个常见误解：下面子图内部的 sub_fetch 仍然用的是 get_stream_writer()，
# 所以【子图那一层依然依赖 contextvar】。实测 3.11+ 下它照常传播，所以 C 跑通了；
# 但如果你要做到【端到端都不依赖 contextvar】（例如必须兼容 Python < 3.11 的
# async 子图），就得把 writer 作为参数一路显式传进子图节点，而不是只在父节点显式。
async def node_c_explicit_writer(state: ParentState, writer: StreamWriter) -> dict:
    writer({"from": "parent", "node": "C", "status": "start",
            "label": "C: 父节点显式 writer 参数（父节点不依赖 contextvar）"})
    # 注意：子图内部仍用 get_stream_writer()，这一层依旧靠 contextvar 传播
    result = await SUBGRAPH.ainvoke({"q": state["query"]})
    writer({"from": "parent", "node": "C", "status": "done"})
    return {"docs_c": result["docs"]}


def build_parent():
    g = StateGraph(ParentState)
    g.add_node("A", node_a_ainvoke)
    g.add_node("B", node_b_ainvoke)
    g.add_node("C", node_c_explicit_writer)
    g.add_edge(START, "A")
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    g.add_edge("C", END)
    return g.compile()


async def main() -> None:
    print(f"Python: {sys.version.split()[0]}  "
          f"(contextvar 自动传播需要 >= 3.11)\n")

    app = build_parent()
    inputs = {"query": "LangGraph async 子图流式"}

    print("=== 父图 astream(subgraphs=True, mode=['custom','updates']) ===\n")
    async for ns, mode, chunk in app.astream(
        inputs,
        stream_mode=["custom", "updates"],
        subgraphs=True,
    ):
        ns_label = "根" if ns == () else f"子图{ns}"
        tag = "进度" if mode == "custom" else "状态"
        print(f"  [{ns_label}][{tag}] {chunk}")

    print("""
观察要点（实测，Python 3.11+ / LangGraph 1.x）：
  - A / B（均 .ainvoke）：子图 progress 正常带 namespace 冒出，contextvar 传播稳定。
  - C：父节点用显式 writer 参数；子图内部仍用 get_stream_writer()，故子图那层仍靠
       contextvar（3.11+ 实测正常）。要端到端脱离 contextvar，需把 writer 传进子图。
  - 若 3.11+ 下看到子图事件【消失】，排查是否手动切断了上下文
    （create_task / 起线程 / callbacks=None）。

  生产建议：async 编排统一用 .ainvoke()/.astream()；3.11+ 下 get_stream_writer()
  即可，无需 Queue/Redis（除非跨进程）；要跨版本最稳就把 writer 显式传到底。
""")


if __name__ == "__main__":
    asyncio.run(main())