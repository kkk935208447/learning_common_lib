"""AgenticRAG GlobalGraph 骨架。

目标：
    演示 AgenticRAG 架构中 GlobalGraph 的控制平面骨架，
    包括等待态、澄清恢复、调度和最终输出。

关键 API：
    - StateGraph + GlobalState —— 全局编排图
    - interrupt(...) —— 进入 WAITING_CLARIFICATION
    - Command(resume=...) —— 用户补充后恢复

运行命令：
    python 01_global_graph_skeleton.py

预期现象：
    1. 正常查询走 schedule -> finalize -> output
    2. 空查询进入 WAITING_CLARIFICATION，再恢复到 scheduler

生产提醒：
    - Clarify 不应直接跳到 output
    - GlobalGraph 负责控制态，子任务结果只通过引用或外部工件进入
    - 同一任务的恢复必须复用相同的 thread_id
"""
from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt


class GlobalState(TypedDict, total=False):
    task_id: int
    request_id: str
    original_query: str
    resolved_query: str
    global_iteration: int
    replan_count: int
    max_replan_count: int
    waiting_reason: Literal["NONE", "CLARIFICATION"]
    clarification_question: str
    next_action: Literal[
        "schedule", "replan", "clarify", "finalize", "fallback", "output"
    ]
    dag_fingerprint: str
    historical_fingerprints: list[str]
    error: str | None
    final_answer: str


def planner_node(state: GlobalState) -> dict:
    """规划节点：分析查询，决定下一步动作。"""
    query = state.get("resolved_query") or state.get("original_query", "")
    iteration = state.get("global_iteration", 0)
    replan_count = state.get("replan_count", 0)
    max_replan = state.get("max_replan_count", 3)

    print(f"[planner] 查询: {query}, 迭代: {iteration}, 重规划: {replan_count}")

    if not query:
        return {
            "next_action": "clarify",
            "waiting_reason": "CLARIFICATION",
            "clarification_question": "请补充更具体的检索目标",
            "error": "查询为空",
        }

    if replan_count >= max_replan:
        print(f"[planner] 达到最大重规划次数 {max_replan}，降级处理")
        return {"next_action": "fallback"}

    return {
        "resolved_query": query,
        "next_action": "schedule",
        "global_iteration": iteration + 1,
        "waiting_reason": "NONE",
    }


def clarify_node(state: GlobalState) -> dict:
    """进入澄清等待态，恢复后继续调度。"""
    question = state.get("clarification_question", "请补充查询")
    if state.get("resolved_query"):
        print(f"[clarify] 已收到补充信息: {state['resolved_query']}")
        return {"next_action": "schedule", "waiting_reason": "NONE"}

    print(f"[clarify] 需要用户澄清: {question}")
    resolved_query = interrupt({"kind": "clarify", "question": question})
    return {
        "resolved_query": str(resolved_query).strip(),
        "next_action": "schedule",
        "waiting_reason": "NONE",
        "error": None,
    }


def scheduler_node(state: GlobalState) -> dict:
    """调度节点：生成 DAG 指纹并进入 finalize。"""
    query = state.get("resolved_query", "")
    fingerprint = f"dag-{hash(query) % 10000:04d}"
    historical = list(state.get("historical_fingerprints", []))

    if fingerprint in historical:
        print(f"[scheduler] DAG 指纹重复 {fingerprint}，直接汇总")
        return {"next_action": "finalize"}

    historical.append(fingerprint)
    print(f"[scheduler] 生成 DAG 指纹: {fingerprint}")
    print("[scheduler] 调度 READY 子任务...")
    return {
        "dag_fingerprint": fingerprint,
        "historical_fingerprints": historical,
        "next_action": "finalize",
    }


def finalize_node(state: GlobalState) -> dict:
    """终结节点：构造最终回答输入。"""
    answer = f"已完成查询规划与调度: {state.get('resolved_query', '')}"
    print(f"[finalize] {answer}")
    return {"final_answer": answer, "next_action": "output"}


def fallback_node(state: GlobalState) -> dict:
    print("[fallback] 降级处理，返回安全说明")
    return {
        "final_answer": "当前无法继续规划，建议缩小范围后重试。",
        "next_action": "output",
    }


def output_node(state: GlobalState) -> dict:
    print(f"[output] 最终回答: {state.get('final_answer', '')}")
    return {}


def route_by_action(state: GlobalState) -> str:
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


def build_global_graph():
    graph = StateGraph(GlobalState)

    graph.add_node("planner", planner_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("scheduler", scheduler_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("output", output_node)

    graph.set_entry_point("planner")
    graph.add_conditional_edges("planner", route_by_action)
    graph.add_conditional_edges("clarify", route_by_action)
    graph.add_conditional_edges("scheduler", route_by_action)
    graph.add_conditional_edges("finalize", route_by_action)
    graph.add_conditional_edges("fallback", route_by_action)
    graph.add_edge("output", END)

    return graph.compile(checkpointer=MemorySaver())


if __name__ == "__main__":
    app = build_global_graph()

    print("=== AgenticRAG GlobalGraph 骨架演示 ===\n")

    print("--- 场景 1: 正常查询 ---\n")
    normal_config = {"configurable": {"thread_id": "global-normal"}}
    result = app.invoke(
        {
            "original_query": "LangGraph 的记忆系统如何设计？",
            "global_iteration": 0,
            "replan_count": 0,
            "max_replan_count": 3,
            "waiting_reason": "NONE",
            "historical_fingerprints": [],
            "final_answer": "",
        },
        config=normal_config,
    )
    print(f"\n最终回答: {result.get('final_answer')}\n")

    print("--- 场景 2: 空查询（触发澄清 -> 恢复）---\n")
    clarify_config = {"configurable": {"thread_id": "global-clarify"}}
    waiting = app.invoke(
        {
            "original_query": "",
            "global_iteration": 0,
            "replan_count": 0,
            "max_replan_count": 3,
            "waiting_reason": "NONE",
            "historical_fingerprints": [],
            "final_answer": "",
        },
        config=clarify_config,
    )
    print(f"等待原因: {waiting.get('waiting_reason')}")
    print(f"澄清问题: {waiting.get('clarification_question')}")

    resumed = app.invoke(Command(resume="LangGraph 的多层记忆设计"), config=clarify_config)
    print(f"\n恢复后最终回答: {resumed.get('final_answer')}")
