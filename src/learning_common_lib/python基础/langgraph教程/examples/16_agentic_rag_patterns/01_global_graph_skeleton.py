"""AgenticRAG GlobalGraph 骨架（等待/恢复主链路版）。

目标：
    演示 GlobalGraph 的两种等待态：
    - WAITING_CLARIFICATION
    - WAITING_SUBTASKS

关键 API：
    - interrupt / Command(resume=...)
    - 同一 thread_id 恢复
    - 最小控制字段：waiting_reason / current_execution_id / latest_result_ref / next_action

运行命令：
    python 01_global_graph_skeleton.py

预期现象：
    1. 正常查询会进入 WAITING_SUBTASKS，外部结果回写后继续 finalize
    2. 空查询会先进入 WAITING_CLARIFICATION，补充后再进入 WAITING_SUBTASKS

生产提醒：
    - 这已经比 toy baseline 更接近真实控制面，但仍然故意省略了 MySQL 真理源、task_events、预算和 replan 细节
    - 父图不在图内等待 worker `.get()`，而是 interrupt 后由外部恢复
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

try:
    from ...templates import CheckpointManager, DEFAULT_RUNTIME_SETTINGS
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import CheckpointManager, DEFAULT_RUNTIME_SETTINGS


class GlobalState(TypedDict, total=False):
    task_id: int
    request_id: str
    original_query: str
    resolved_query: str
    waiting_reason: Literal["NONE", "CLARIFICATION", "SUBTASKS"]
    clarification_question: str
    current_execution_id: str
    latest_result_ref: dict | None
    next_action: Literal["clarify", "schedule", "wait_subtasks", "step_gate", "finalize", "output", "fallback"]
    final_answer: str


def planner_node(state: GlobalState) -> dict:
    query = state.get("resolved_query") or state.get("original_query", "")
    print(f"[planner] original_query={state.get('original_query')!r} resolved_query={state.get('resolved_query')!r}")
    if not query:
        return {
            "next_action": "clarify",
            "waiting_reason": "CLARIFICATION",
            "clarification_question": "请补充你关心的时间范围或对象范围",
        }
    return {
        "resolved_query": query,
        "waiting_reason": "NONE",
        "next_action": "schedule",
    }


def clarify_node(state: GlobalState) -> dict:
    if state.get("resolved_query"):
        print(f"[clarify] 已有 resolved_query={state['resolved_query']}")
        return {"next_action": "schedule", "waiting_reason": "NONE"}
    payload = {
        "kind": "clarify",
        "question": state.get("clarification_question", "请补充查询"),
    }
    print(f"[clarify] interrupt payload={payload}")
    resolved_query = interrupt(payload)
    return {
        "resolved_query": str(resolved_query).strip(),
        "waiting_reason": "NONE",
        "next_action": "schedule",
    }


def scheduler_node(state: GlobalState) -> dict:
    execution_id = f"exec-{state['task_id']}-001"
    print(
        "[scheduler] 生成 execution_ref: "
        f"task_id={state['task_id']} current_execution_id={execution_id}"
    )
    return {
        "current_execution_id": execution_id,
        "waiting_reason": "SUBTASKS",
        "next_action": "wait_subtasks",
    }


def wait_subtasks_node(state: GlobalState) -> dict:
    if state.get("latest_result_ref"):
        print(f"[wait_subtasks] 已有 latest_result_ref={state['latest_result_ref']}")
        return {"next_action": "step_gate", "waiting_reason": "NONE"}
    payload = {
        "kind": "subtask_result",
        "execution_id": state["current_execution_id"],
        "waiting_reason": state["waiting_reason"],
    }
    print(f"[wait_subtasks] interrupt payload={payload}")
    resume_payload = interrupt(payload)
    return {
        "latest_result_ref": resume_payload,
        "waiting_reason": "NONE",
        "next_action": "step_gate",
    }


def step_gate_node(state: GlobalState) -> dict:
    print(
        "[step_gate] current_execution_id="
        f"{state.get('current_execution_id')} latest_result_ref={state.get('latest_result_ref')}"
    )
    if state.get("latest_result_ref"):
        return {"next_action": "finalize"}
    return {"next_action": "fallback"}


def finalize_node(state: GlobalState) -> dict:
    latest = state.get("latest_result_ref") or {}
    answer = (
        f"已完成查询：{state.get('resolved_query', '')} | "
        f"引用结果={latest.get('result_ref')} summary={latest.get('summary')}"
    )
    print(f"[finalize] {answer}")
    return {"final_answer": answer, "next_action": "output"}


def fallback_node(_: GlobalState) -> dict:
    print("[fallback] 当前没有足够结果，返回安全说明")
    return {"final_answer": "当前无法完成，请稍后重试。", "next_action": "output"}


def output_node(state: GlobalState) -> dict:
    print(f"[output] final_answer={state.get('final_answer')}")
    return {}


def route_by_action(state: GlobalState) -> str:
    action = state.get("next_action", "fallback")
    mapping = {
        "clarify": "clarify",
        "schedule": "scheduler",
        "wait_subtasks": "wait_subtasks",
        "step_gate": "step_gate",
        "finalize": "finalize",
        "output": "output",
        "fallback": "fallback",
    }
    target = mapping.get(action, "fallback")
    print(f"[route] next_action={action} -> {target}")
    return target


def build_global_graph(checkpointer):
    graph = StateGraph(GlobalState)
    graph.add_node("planner", planner_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("scheduler", scheduler_node)
    graph.add_node("wait_subtasks", wait_subtasks_node)
    graph.add_node("step_gate", step_gate_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("output", output_node)
    graph.set_entry_point("planner")
    graph.add_conditional_edges("planner", route_by_action)
    graph.add_conditional_edges("clarify", route_by_action)
    graph.add_conditional_edges("scheduler", route_by_action)
    graph.add_conditional_edges("wait_subtasks", route_by_action)
    graph.add_conditional_edges("step_gate", route_by_action)
    graph.add_conditional_edges("finalize", route_by_action)
    graph.add_conditional_edges("fallback", route_by_action)
    graph.add_edge("output", END)
    return graph.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    async def main() -> None:
        checkpoint_mgr = CheckpointManager()
        checkpointer = await checkpoint_mgr.get_checkpointer()
        app = build_global_graph(checkpointer)

        print("=== 场景 1：正常查询 -> WAITING_SUBTASKS -> 恢复 ===\n")
        thread_normal = DEFAULT_RUNTIME_SETTINGS.demo_thread_id("global-normal")
        config_normal = {"configurable": {"thread_id": thread_normal}}
        waiting = await app.ainvoke(
            {
                "task_id": 101,
                "request_id": "req-101",
                "original_query": "整理近 30 天差旅规则变化",
                "waiting_reason": "NONE",
            },
            config=config_normal,
        )
        print(f"waiting_reason={waiting.get('waiting_reason')} current_execution_id={waiting.get('current_execution_id')}\n")
        resumed = await app.ainvoke(
            Command(
                resume={
                    "execution_id": waiting["current_execution_id"],
                    "result_ref": "run://3001",
                    "summary": "worker 已完成 evidence merge",
                }
            ),
            config=config_normal,
        )
        print(f"final_answer={resumed.get('final_answer')}\n")

        print("=== 场景 2：空查询 -> WAITING_CLARIFICATION -> WAITING_SUBTASKS -> 恢复 ===\n")
        thread_clarify = DEFAULT_RUNTIME_SETTINGS.demo_thread_id("global-clarify")
        config_clarify = {"configurable": {"thread_id": thread_clarify}}
        clarify_wait = await app.ainvoke(
            {
                "task_id": 202,
                "request_id": "req-202",
                "original_query": "",
                "waiting_reason": "NONE",
            },
            config=config_clarify,
        )
        print(
            f"clarify_wait waiting_reason={clarify_wait.get('waiting_reason')} "
            f"question={clarify_wait.get('clarification_question')}\n"
        )
        subtask_wait = await app.ainvoke(
            Command(resume="整理近 7 天差旅规则变化"),
            config=config_clarify,
        )
        print(
            f"after clarify waiting_reason={subtask_wait.get('waiting_reason')} "
            f"current_execution_id={subtask_wait.get('current_execution_id')}\n"
        )
        done = await app.ainvoke(
            Command(
                resume={
                    "execution_id": subtask_wait["current_execution_id"],
                    "result_ref": "run://4001",
                    "summary": "worker 已完成最近 7 天变化提取",
                }
            ),
            config=config_clarify,
        )
        print(f"final_answer={done.get('final_answer')}")

        await checkpoint_mgr.aclose()

    asyncio.run(main())
