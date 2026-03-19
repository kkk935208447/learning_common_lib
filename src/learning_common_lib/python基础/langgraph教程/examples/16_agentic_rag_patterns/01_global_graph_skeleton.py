"""AgenticRAG GlobalGraph 骨架。

目标：
    演示 AgenticRAG 架构中 GlobalGraph 的控制平面骨架，
    包括等待态、澄清恢复、调度和最终输出，并以 Redis-first checkpoint 作为运行时基线。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

try:
    from ...templates import (
        CheckpointManager,
        DEFAULT_RUNTIME_SETTINGS,
    )
except ImportError:  # pragma: no cover - 允许直接运行脚本
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import (
        CheckpointManager,
        DEFAULT_RUNTIME_SETTINGS,
    )


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
    next_action: Literal["schedule", "replan", "clarify", "finalize", "fallback", "output"]
    dag_fingerprint: str
    historical_fingerprints: list[str]
    error: str | None
    final_answer: str


def planner_node(state: GlobalState) -> dict:
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


def build_global_graph(checkpointer):
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
    return graph.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    async def main() -> None:
        checkpoint_mgr = CheckpointManager()
        checkpointer = await checkpoint_mgr.get_checkpointer()
        app = build_global_graph(checkpointer)
        normal_thread_id = DEFAULT_RUNTIME_SETTINGS.demo_thread_id("global-normal")
        clarify_thread_id = DEFAULT_RUNTIME_SETTINGS.demo_thread_id("global-clarify")

        print("=== AgenticRAG GlobalGraph 骨架演示 ===\n")
        print(
            f"checkpoint_backend={checkpoint_mgr.backend} "
            f"checkpoint_degraded={checkpoint_mgr.degraded} "
            f"last_error={checkpoint_mgr.last_error}"
        )

        print("--- 场景 1: 正常查询 ---\n")
        normal_config = {
            "configurable": {
                "thread_id": normal_thread_id,
            }
        }
        result = await app.ainvoke(
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
        clarify_config = {
            "configurable": {
                "thread_id": clarify_thread_id,
            }
        }
        waiting = await app.ainvoke(
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
        if waiting.get("waiting_reason") != "CLARIFICATION":
            raise RuntimeError(
                "澄清场景未进入等待态；请检查 thread_id 是否被复用，或 checkpoint 恢复了旧状态"
            )
        print(f"等待原因: {waiting.get('waiting_reason')}")
        print(f"澄清问题: {waiting.get('clarification_question')}")

        resumed = await app.ainvoke(Command(resume="LangGraph 的多层记忆设计"), config=clarify_config)
        print(f"\n恢复后最终回答: {resumed.get('final_answer')}")

        await checkpoint_mgr.aclose()

    asyncio.run(main())
