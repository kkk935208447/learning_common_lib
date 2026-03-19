"""生产级图构建工厂：统一节点注册、边配置、编译选项。"""
from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .safe_node import safe_node

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GraphBuilder
# ---------------------------------------------------------------------------

class GraphBuilder:
    """生产级图构建工厂。

    用法::

        builder = GraphBuilder(state_schema=MyState)
        builder.add_node("agent", agent_fn)
        builder.add_node("tool", tool_fn, safe=True, timeout_s=10)
        builder.add_conditional_routing("agent", router, {"continue": "tool", "end": END})
        builder.set_entry("agent")
        graph = builder.build()
    """

    def __init__(
        self,
        state_schema: type,
        checkpointer: Any | None = None,
    ) -> None:
        self._builder = StateGraph(state_schema)
        self._checkpointer = checkpointer
        self._nodes: dict[str, Callable] = {}
        self._entry: str | None = None

    # -- 节点 --

    def add_node(
        self,
        name: str,
        func: Callable,
        *,
        safe: bool = True,
        timeout_s: float = 30,
    ) -> GraphBuilder:
        """注册节点，可选 safe_node 包装。"""
        wrapped = func
        if safe:
            wrapped = safe_node(node_name=name, timeout_s=timeout_s)(func)
        self._builder.add_node(name, wrapped)
        self._nodes[name] = wrapped
        return self

    # -- 边 --

    def add_edge(self, source: str, target: str) -> GraphBuilder:
        """添加普通边。"""
        self._builder.add_edge(source, target)
        return self

    def add_conditional_routing(
        self,
        source: str,
        router_fn: Callable,
        mapping: dict[str, str],
    ) -> GraphBuilder:
        """添加条件路由。"""
        self._builder.add_conditional_edges(source, router_fn, mapping)
        return self

    # -- 入口 --

    def set_entry(self, name: str) -> GraphBuilder:
        """设置入口节点。"""
        self._entry = name
        self._builder.set_entry_point(name)
        return self

    # -- 编译 --

    def build(self) -> CompiledStateGraph:
        """编译图。"""
        kwargs: dict[str, Any] = {}
        if self._checkpointer:
            kwargs["checkpointer"] = self._checkpointer
        return self._builder.compile(**kwargs)


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def build_graph(
    state_schema: type,
    nodes: dict[str, Callable],
    edges: list[tuple[str, str]],
    entry: str,
    checkpointer: Any | None = None,
) -> CompiledStateGraph:
    """一行构建简单线性图。"""
    gb = GraphBuilder(state_schema, checkpointer=checkpointer)
    for name, func in nodes.items():
        gb.add_node(name, func)
    for src, tgt in edges:
        gb.add_edge(src, tgt)
    gb.set_entry(entry)
    return gb.build()


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    """演示 GraphBuilder 的基本用法。"""
    from typing import TypedDict

    class DemoState(TypedDict, total=False):
        value: int
        error: str | None

    async def step_a(state: dict) -> dict:
        print(f"  step_a: value={state.get('value', 0)}")
        return {"value": state.get("value", 0) + 1}

    async def step_b(state: dict) -> dict:
        print(f"  step_b: value={state.get('value', 0)}")
        return {"value": state.get("value", 0) * 10}

    graph = (
        GraphBuilder(DemoState)
        .add_node("a", step_a)
        .add_node("b", step_b)
        .add_edge("a", "b")
        .set_entry("a")
        .build()
    )

    import asyncio

    result = asyncio.run(graph.ainvoke({"value": 1}))
    print(f"  最终结果: {result}")


if __name__ == "__main__":
    _demo()
