"""AgenticRAG GlobalGraph 骨架

目标：
    演示 AgenticRAG 架构中 GlobalGraph 的骨架设计，
    包括全局状态定义、核心节点和路由逻辑。

关键 API：
    - StateGraph + GlobalState —— 全局编排图
    - Command —— 动作路由
    - next_action 驱动的状态机

运行命令：
    python 01_global_graph_skeleton.py

预期现象：
    GlobalGraph 根据 next_action 在不同节点间流转，
    模拟 schedule → execute → finalize 的完整流程。

生产提醒：
    - GlobalState 的字段设计直接影响系统的可扩展性
    - max_replan_count 防止无限循环，生产环境必须设置
    - dag_fingerprint 用于检测 DAG 变化，避免重复执行
"""
from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph


# ══════════════════════════════════════════════════════════
# GlobalState 定义
# ══════════════════════════════════════════════════════════

class GlobalState(TypedDict, total=False):
    """全局编排状态

    这是 AgenticRAG 的核心状态定义，驱动整个编排流程。
    """
    task_id: int                    # 任务 ID
    request_id: str                 # 请求追踪 ID
    original_query: str             # 用户原始查询
    resolved_query: str             # 解析/改写后的查询
    global_iteration: int           # 全局迭代次数
    replan_count: int               # 重规划次数
    max_replan_count: int           # 最大重规划次数（防无限循环）
    next_action: Literal[           # 下一步动作（状态机驱动）
        "schedule", "replan", "clarify", "finalize", "fallback", "output"
    ]
    dag_fingerprint: str            # 当前 DAG 指纹（检测变化）
    historical_fingerprints: list[str]  # 历史 DAG 指纹
    error: str | None               # 错误信息


# ── 节点函数 ──────────────────────────────────────────────
def planner_node(state: GlobalState) -> dict:
    """规划节点：分析查询，决定下一步动作"""
    query = state.get("original_query", "")
    iteration = state.get("global_iteration", 0)
    replan_count = state.get("replan_count", 0)
    max_replan = state.get("max_replan_count", 3)

    print(f"[planner] 查询: {query}, 迭代: {iteration}, 重规划: {replan_count}")

    # 规划逻辑
    if not query:
        return {"next_action": "clarify", "error": "查询为空"}

    if replan_count >= max_replan:
        print(f"[planner] 达到最大重规划次数 {max_replan}，降级处理")
        return {"next_action": "fallback"}

    # 首次执行 → schedule，后续 → 检查是否需要 replan
    if iteration == 0:
        return {
            "next_action": "schedule",
            "resolved_query": query,  # 简化：直接使用原始查询
            "global_iteration": 1,
        }
    else:
        return {"next_action": "finalize"}


def scheduler_node(state: GlobalState) -> dict:
    """调度节点：生成 DAG 并分发子任务"""
    query = state.get("resolved_query", "")
    fingerprint = f"dag-{hash(query) % 10000:04d}"

    historical = list(state.get("historical_fingerprints", []))
    if fingerprint in historical:
        print(f"[scheduler] DAG 指纹重复 {fingerprint}，跳过")
        return {"next_action": "finalize"}

    historical.append(fingerprint)
    print(f"[scheduler] 生成 DAG 指纹: {fingerprint}")
    print(f"[scheduler] 分发子任务...")

    # 模拟子任务执行完成后回到 planner
    return {
        "dag_fingerprint": fingerprint,
        "historical_fingerprints": historical,
        "next_action": "finalize",
        "global_iteration": state.get("global_iteration", 0) + 1,
    }


def clarify_node(state: GlobalState) -> dict:
    """澄清节点：查询不明确时请求用户补充"""
    print(f"[clarify] 需要用户澄清: {state.get('error', '未知原因')}")
    return {"next_action": "output"}


def finalize_node(state: GlobalState) -> dict:
    """终结节点：汇总结果，生成最终输出"""
    print(f"[finalize] 汇总结果，查询: {state.get('resolved_query', '')}")
    return {"next_action": "output"}


def fallback_node(state: GlobalState) -> dict:
    """降级节点：无法正常处理时的兜底逻辑"""
    print(f"[fallback] 降级处理，原因: 超过最大重规划次数")
    return {"next_action": "output"}


def output_node(state: GlobalState) -> dict:
    """输出节点：格式化最终结果"""
    action = state.get("next_action", "unknown")
    print(f"[output] 输出最终结果（来自: {action}）")
    return {}


# ── 路由函数 ──────────────────────────────────────────────
def route_by_action(state: GlobalState) -> str:
    """根据 next_action 路由到对应节点"""
    action = state.get("next_action", "fallback")
    route_map = {
        "schedule": "scheduler",
        "replan": "planner",
        "clarify": "clarify",
        "finalize": "finalize",
        "fallback": "fallback",
        "output": "output",
    }
    target = route_map.get(action, "fallback")
    print(f"[route] {action} -> {target}")
    return target


# ── 构建 GlobalGraph ──────────────────────────────────────
def build_global_graph():
    graph = StateGraph(GlobalState)

    graph.add_node("planner", planner_node)
    graph.add_node("scheduler", scheduler_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("output", output_node)

    graph.set_entry_point("planner")

    # planner 根据 next_action 路由
    graph.add_conditional_edges("planner", route_by_action)
    # scheduler 完成后回到 planner（可能需要 replan）
    graph.add_conditional_edges("scheduler", route_by_action)
    # 其他节点都指向 output 或通过 route
    graph.add_conditional_edges("clarify", route_by_action)
    graph.add_conditional_edges("finalize", route_by_action)
    graph.add_conditional_edges("fallback", route_by_action)
    graph.add_edge("output", END)

    return graph.compile()


if __name__ == "__main__":
    app = build_global_graph()

    print("=== AgenticRAG GlobalGraph 骨架演示 ===\n")

    # 正常流程
    print("--- 场景 1: 正常查询 ---\n")
    result = app.invoke({
        "original_query": "LangGraph 的记忆系统如何设计？",
        "global_iteration": 0,
        "replan_count": 0,
        "max_replan_count": 3,
        "historical_fingerprints": [],
    })
    print(f"\n最终状态: next_action={result.get('next_action')}\n")

    # 空查询（触发 clarify）
    print("--- 场景 2: 空查询（触发澄清）---\n")
    result2 = app.invoke({
        "original_query": "",
        "global_iteration": 0,
        "replan_count": 0,
        "max_replan_count": 3,
        "historical_fingerprints": [],
    })
    print(f"\n最终状态: next_action={result2.get('next_action')}")
