"""调试技巧：状态检查、Mermaid 图

目标：
    演示 LangGraph 的调试工具：运行时状态检查、Mermaid 图可视化、
    步骤追踪等实用调试技巧。

关键 API：
    - graph.get_state(config) —— 获取当前状态快照
    - graph.get_state_history(config) —— 获取状态历史
    - graph.get_graph().draw_mermaid() —— 生成 Mermaid 图
    - stream mode "debug" —— 详细调试信息

运行命令：
    python 04_debug_visualization.py

预期现象：
    输出 Mermaid 图定义、状态快照、执行历史等调试信息。

生产提醒：
    - Mermaid 图可粘贴到 GitHub/Notion 等支持 Mermaid 的平台渲染
    - get_state_history 在大量 checkpoint 时可能较慢，建议限制查询范围
    - 生产环境建议集成 LangSmith 进行全链路追踪
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph


# ── 被调试的图 ──────────────────────────────────────────
class DebugState(TypedDict):
    input: str
    step1_result: str
    step2_result: str
    final: str


def step1(state: DebugState) -> dict:
    result = f"step1({state['input']})"
    return {"step1_result": result}


def step2(state: DebugState) -> dict:
    result = f"step2({state['step1_result']})"
    return {"step2_result": result}


def finalize(state: DebugState) -> dict:
    result = f"final({state['step2_result']})"
    return {"final": result}


def build_debug_graph():
    graph = StateGraph(DebugState)
    graph.add_node("step1", step1)
    graph.add_node("step2", step2)
    graph.add_node("finalize", finalize)
    graph.set_entry_point("step1")
    graph.add_edge("step1", "step2")
    graph.add_edge("step2", "finalize")
    graph.add_edge("finalize", END)
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer), graph


# ══════════════════════════════════════════════════════════
# 调试技巧
# ══════════════════════════════════════════════════════════

def debug_mermaid(graph: StateGraph) -> None:
    """技巧 1：生成 Mermaid 图"""
    print("--- 技巧 1: Mermaid 可视化 ---\n")
    try:
        mermaid_str = graph.get_graph().draw_mermaid()
        print("将以下内容粘贴到支持 Mermaid 的平台（GitHub, Notion 等）:\n")
        print("```mermaid")
        print(mermaid_str)
        print("```\n")
    except Exception as e:
        print(f"  Mermaid 生成失败（可能缺少依赖）: {e}\n")


def debug_state_inspection(app, config: dict) -> None:
    """技巧 2：运行时状态检查"""
    print("--- 技巧 2: 状态检查 ---\n")
    state = app.get_state(config)
    print(f"  当前状态值: {state.values}")
    print(f"  下一步节点: {state.next}")
    print(f"  配置: {state.config}\n")


def debug_state_history(app, config: dict) -> None:
    """技巧 3：状态历史追踪"""
    print("--- 技巧 3: 状态历史 ---\n")
    history = list(app.get_state_history(config))
    print(f"  共 {len(history)} 个历史状态:\n")
    for i, snapshot in enumerate(reversed(history)):
        values = snapshot.values
        print(f"  [{i}] next={snapshot.next}")
        for k, v in values.items():
            if v:  # 只显示非空值
                print(f"       {k}: {v}")
        print()


def debug_stream_updates(app, initial_state: dict, config: dict) -> None:
    """技巧 4：流式追踪每步更新"""
    print("--- 技巧 4: 流式步骤追踪 ---\n")
    for event in app.stream(initial_state, config=config, stream_mode="updates"):
        for node_name, update in event.items():
            print(f"  节点 [{node_name}] 更新: {update}")
    print()


if __name__ == "__main__":
    app, graph_builder = build_debug_graph()
    config = {"configurable": {"thread_id": "debug-demo"}}

    print("=== LangGraph 调试技巧 ===\n")

    # 技巧 1：Mermaid 图
    debug_mermaid(graph_builder)

    # 技巧 4：流式追踪（同时执行图）
    initial = {"input": "hello", "step1_result": "", "step2_result": "", "final": ""}
    debug_stream_updates(app, initial, config)

    # 技巧 2：状态检查（图执行完毕后）
    debug_state_inspection(app, config)

    # 技巧 3：状态历史
    debug_state_history(app, config)

    print("提示: 生产环境建议集成 LangSmith 进行全链路追踪和性能分析")
