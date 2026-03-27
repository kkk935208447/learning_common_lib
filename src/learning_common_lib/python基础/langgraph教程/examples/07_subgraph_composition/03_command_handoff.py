"""
07_subgraph_composition / 03_command_handoff

目标:
    使用 Command 原语实现子图间控制权移交 (handoff)

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    Command(goto=..., update=...)

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/07_subgraph_composition/03_command_handoff.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/07_subgraph_composition/03_command_handoff.py

预期现象:
    请求从 triage 节点根据类型分发到不同子图，子图处理后通过 Command 移交控制权

生产提醒:
    Command 是 AgenticRAG escalation 模式的核心原语，可跨子图边界传递控制
"""
from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class MainState(TypedDict, total=False):
    query: str
    category: str
    result: str
    escalated: bool


# ---------------------------------------------------------------------------
# 子图 A：简单查询处理
# ---------------------------------------------------------------------------

def simple_handler(state: MainState) -> Command[Literal["post_process"]]:
    """处理简单查询，完成后移交给 post_process"""
    query = state.get("query", "")
    print(f"[简单处理器] 处理: {query}")
    # 通过 Command 移交控制权并更新状态
    return Command(
        goto="post_process",
        update={"result": f"简单回答: {query} 的结果", "escalated": False},
    )


# ---------------------------------------------------------------------------
# 子图 B：复杂查询处理
# ---------------------------------------------------------------------------

def complex_handler(state: MainState) -> Command[Literal["post_process"]]:
    """处理复杂查询，完成后移交给 post_process"""
    query = state.get("query", "")
    print(f"[复杂处理器] 深度分析: {query}")
    return Command(
        goto="post_process",
        update={"result": f"深度分析: {query} 的详细结果", "escalated": False},
    )


# ---------------------------------------------------------------------------
# 子图 C：升级处理（模拟 AgenticRAG escalation）
# ---------------------------------------------------------------------------

def escalation_handler(state: MainState) -> Command[Literal["post_process"]]:
    """升级处理：标记需要人工介入"""
    query = state.get("query", "")
    print(f"[升级处理器] 升级请求: {query}")
    return Command(
        goto="post_process",
        update={
            "result": f"已升级: {query} 需要人工审核",
            "escalated": True,
        },
    )


# ---------------------------------------------------------------------------
# 分流节点
# ---------------------------------------------------------------------------

def triage(state: MainState) -> Command[Literal["simple", "complex", "escalate"]]:
    """根据查询类型分流到不同处理器"""
    query = state.get("query", "")
    # 简单的分类逻辑
    if "简单" in query:
        category = "simple"
    elif "复杂" in query:
        category = "complex"
    else:
        category = "escalate"
    print(f"[分流] query='{query}' → {category}")
    return Command(goto=category, update={"category": category})


# ---------------------------------------------------------------------------
# 后处理节点
# ---------------------------------------------------------------------------

def post_process(state: MainState) -> dict:
    """统一后处理"""
    escalated = state.get("escalated", False)
    tag = "需人工跟进" if escalated else "已完成"
    print(f"[后处理] 状态={tag}")
    return {"result": f"[{tag}] {state.get('result', '')}"}


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------

builder = StateGraph(MainState)
builder.add_node("triage", triage)
builder.add_node("simple", simple_handler)
builder.add_node("complex", complex_handler)
builder.add_node("escalate", escalation_handler)
builder.add_node("post_process", post_process)

builder.add_edge(START, "triage")
# triage 通过 Command 动态路由，无需显式条件边
builder.add_edge("post_process", END)

graph = builder.compile()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    for q in ["简单问题", "复杂分析任务", "未知类型请求"]:
        print(f"\n{'='*50}")
        print(f"查询: {q}")
        result = graph.invoke({"query": q})
        print(f"结果: {result.get('result', '')}")
