"""
09_error_and_resilience / 03_fallback_chain

目标:
    多级降级链 — 主路径→备选→兜底，参考 AgenticRAG 的 DEGRADED 状态

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    条件边 + 降级状态标记

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/09_error_and_resilience/03_fallback_chain.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/09_error_and_resilience/03_fallback_chain.py

预期现象:
    主路径失败时自动切换到备选方案，备选也失败则使用兜底方案

生产提醒:
    降级链确保系统在部分组件故障时仍能提供有限服务，而非完全不可用
"""
from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class State(TypedDict, total=False):
    query: str
    result: str
    quality: str       # "full" | "degraded" | "minimal"
    primary_ok: bool
    fallback_ok: bool


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------

def primary_handler(state: State) -> dict:
    """主路径：调用高质量模型"""
    query = state.get("query", "")
    # 模拟主路径失败
    success = "简单" in query
    print(f"[主路径] query='{query}', success={success}")
    if success:
        return {"result": f"高质量回答: {query}", "quality": "full", "primary_ok": True}
    return {"primary_ok": False}


def fallback_handler(state: State) -> dict:
    """备选路径：调用轻量模型"""
    query = state.get("query", "")
    # 模拟备选也可能失败
    success = "中等" in query or "简单" in query
    print(f"[备选路径] query='{query}', success={success}")
    if success:
        return {"result": f"备选回答: {query}", "quality": "degraded", "fallback_ok": True}
    return {"fallback_ok": False}


def safety_net(state: State) -> dict:
    """兜底方案：返回预设回复"""
    print("[兜底] 使用预设回复")
    return {
        "result": "抱歉，当前服务受限，请稍后重试或联系人工客服",
        "quality": "minimal",
    }


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

def after_primary(state: State) -> Literal["fallback", "__end__"]:
    if state.get("primary_ok"):
        return "__end__"
    return "fallback"


def after_fallback(state: State) -> Literal["safety_net", "__end__"]:
    if state.get("fallback_ok"):
        return "__end__"
    return "safety_net"


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------

builder = StateGraph(State)
builder.add_node("primary", primary_handler)
builder.add_node("fallback", fallback_handler)
builder.add_node("safety_net", safety_net)

builder.add_edge(START, "primary")
builder.add_conditional_edges("primary", after_primary, {"fallback": "fallback", "__end__": END})
builder.add_conditional_edges("fallback", after_fallback, {"safety_net": "safety_net", "__end__": END})
builder.add_edge("safety_net", END)

graph = builder.compile()


def get_langgraph_png(app: StateGraph, file_name: str) -> None:
    from pathlib import Path
    PARENT_DIR = Path(__file__).resolve().parent   # 获得当前文件的父目录
    FILE_PATH = str(PARENT_DIR / file_name)
    app.get_graph(xray=True).draw_mermaid_png(output_file_path=FILE_PATH)
    print(f"图已导出到 {FILE_PATH}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    get_langgraph_png(graph, "03_fallback_chain.png") # 导出图

    for q in ["简单问题", "中等难度", "极端复杂场景"]:
        print(f"\n{'='*50}")
        result = graph.invoke({"query": q})
        print(f"quality={result.get('quality')}, result={result.get('result')}")
