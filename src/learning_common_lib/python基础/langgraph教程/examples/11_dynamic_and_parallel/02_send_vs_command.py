"""Send vs Command 对比：何时用哪个

目标：
    对比 Send 和 Command 两种路由机制的适用场景。
    Send = 并行 fan-out（一对多），Command = 单路由 handoff（一对一）。

关键 API：
    - Send(node, state) —— 并行分发，创建多个分支
    - Command(goto, update) —— 单路由跳转，可附带状态更新

运行命令：
    python 02_send_vs_command.py

预期现象：
    分别演示 Send 并行处理和 Command 单路由跳转，对比两者行为差异。

生产提醒：
    - Send 适合 map-reduce、并行搜索等场景
    - Command 适合条件路由、agent handoff、工具调用后跳转
    - 两者不要混用：一个节点要么返回 list[Send]，要么返回 Command
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command, Send


# ══════════════════════════════════════════════════════════
# 方案 A：Send —— 并行 fan-out
# ══════════════════════════════════════════════════════════

class SendState(TypedDict):
    items: list[str]
    results: Annotated[list[str], operator.add]


class ItemState(TypedDict):
    item: str


def send_dispatcher(state: SendState) -> list[Send]:
    """一次性分发所有 item 到 worker，并行执行"""
    print(f"[Send 模式] 并行分发 {len(state['items'])} 个任务")
    return [Send("send_worker", {"item": item}) for item in state["items"]]


def send_worker(state: ItemState) -> dict:
    result = f"Send处理: {state['item']}"
    print(f"  [Send worker] {result}")
    return {"results": [result]}


def build_send_graph() -> StateGraph:
    g = StateGraph(SendState)
    g.add_node("dispatcher", send_dispatcher)
    g.add_node("send_worker", send_worker)
    g.set_entry_point("dispatcher")
    g.add_conditional_edges("dispatcher", send_dispatcher, ["send_worker"])
    g.add_edge("send_worker", END)
    return g.compile()


# ══════════════════════════════════════════════════════════
# 方案 B：Command —— 单路由 handoff
# ══════════════════════════════════════════════════════════

class CmdState(TypedDict):
    query: str
    category: str
    answer: str


def classifier(state: CmdState) -> Command:
    """根据 query 内容路由到不同处理节点（一对一）"""
    query = state["query"]
    if "价格" in query or "多少钱" in query:
        cat = "pricing"
    elif "故障" in query or "报错" in query:
        cat = "support"
    else:
        cat = "general"
    print(f"[Command 模式] 分类为 '{cat}'，单路由跳转")
    # Command 跳转到指定节点，同时更新状态
    return Command(goto=cat, update={"category": cat})


def pricing_handler(state: CmdState) -> dict:
    print("  [pricing] 处理价格咨询")
    return {"answer": f"价格咨询回复: {state['query']}"}


def support_handler(state: CmdState) -> dict:
    print("  [support] 处理技术支持")
    return {"answer": f"技术支持回复: {state['query']}"}


def general_handler(state: CmdState) -> dict:
    print("  [general] 处理通用问题")
    return {"answer": f"通用回复: {state['query']}"}


def build_command_graph() -> StateGraph:
    g = StateGraph(CmdState)
    g.add_node("classifier", classifier)
    g.add_node("pricing", pricing_handler)
    g.add_node("support", support_handler)
    g.add_node("general", general_handler)
    g.set_entry_point("classifier")
    # Command 内部已指定 goto，无需 add_edge 从 classifier 出发
    g.add_edge("pricing", END)
    g.add_edge("support", END)
    g.add_edge("general", END)
    return g.compile()


# ── 对比总结 ──────────────────────────────────────────────
COMPARISON = """
┌──────────┬──────────────────────┬──────────────────────┐
│          │ Send                 │ Command              │
├──────────┼──────────────────────┼──────────────────────┤
│ 分支数   │ 一对多（并行）       │ 一对一（单路由）     │
│ 返回类型 │ list[Send]           │ Command              │
│ 典型场景 │ map-reduce, 并行搜索 │ agent handoff, 路由  │
│ 状态隔离 │ 每个分支独立副本     │ 共享同一状态         │
│ 聚合方式 │ reducer 自动合并     │ 不需要聚合           │
└──────────┴──────────────────────┴──────────────────────┘
"""


if __name__ == "__main__":
    print("=" * 50)
    print("方案 A: Send 并行 fan-out")
    print("=" * 50)
    send_app = build_send_graph()
    r1 = send_app.invoke({"items": ["任务A", "任务B", "任务C"], "results": []})
    print(f"结果: {r1['results']}\n")

    print("=" * 50)
    print("方案 B: Command 单路由 handoff")
    print("=" * 50)
    cmd_app = build_command_graph()
    r2 = cmd_app.invoke({"query": "这个产品多少钱？", "category": "", "answer": ""})
    print(f"结果: {r2['answer']}\n")

    print(COMPARISON)
