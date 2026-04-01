"""
08_human_in_the_loop / 06_clarify_with_timeout_default

目标:
    演示 Clarify 的结构化恢复和超时默认项。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    interrupt、Command(resume=...)、默认项 helper

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/08_human_in_the_loop/06_clarify_with_timeout_default.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/08_human_in_the_loop/06_clarify_with_timeout_default.py

预期现象:
    1. 缺少时间范围时进入结构化 Clarify
    2. 超时后可自动应用默认项继续执行
    3. 用户也可以显式回复结构化答案

生产提醒:
    - Clarify 默认项必须显式可审计，不能静默改 query
    - 重复提交时应该基于 clarification_id 做幂等保护
"""
from __future__ import annotations

import asyncio
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class ClarifyState(TypedDict, total=False):
    query: str
    clarification_request: dict
    selected_option_id: str
    final_query: str


def build_default_reply(request: dict) -> dict:
    return {
        "clarification_id": request["clarification_id"],
        "selected_option_id": request["default_option_id"],
        "answer_origin": "DEFAULT_APPLIED",
    }


def planner(state: ClarifyState) -> dict:
    query = state.get("query", "")
    if "近" in query or "30天" in query or "90天" in query:
        return {"selected_option_id": "already_present"}

    return {
        "clarification_request": {
            "clarification_id": "clarify-001",
            "question": "请选择你关心的时间范围",
            "question_type": "SINGLE_SELECT",
            "options": [
                {"id": "opt_30d", "label": "近 30 天"},
                {"id": "opt_90d", "label": "近 90 天"},
            ],
            "default_option_id": "opt_90d",
            "expires_at": "2026-03-26T12:15:00Z",
        }
    }


def wait_for_clarify(state: ClarifyState) -> dict:
    if state.get("selected_option_id"):
        return {}

    clarify_request = state["clarification_request"]
    response = interrupt(clarify_request)
    if response.get("clarification_id") != clarify_request["clarification_id"]:
        raise ValueError("clarification_id 不匹配")
    return {
        "selected_option_id": response["selected_option_id"],
    }


def finalize(state: ClarifyState) -> dict:
    option_id = state.get("selected_option_id", "already_present")
    query = state.get("query", "")
    suffix = {
        "opt_30d": "（时间范围：近 30 天）",
        "opt_90d": "（时间范围：近 90 天）",
        "already_present": "",
    }.get(option_id, "")
    return {"final_query": f"{query}{suffix}"}


def route_after_planner(state: ClarifyState):
    if state.get("selected_option_id") == "already_present":
        return "finalize"
    return "wait"


def route_after_wait(state: ClarifyState):
    if state.get("selected_option_id"):
        return "finalize"
    return "__end__"


async def run_timeout_default(app) -> None:
    config = {"configurable": {"thread_id": "clarify-timeout-demo"}}
    waiting = await app.ainvoke({"query": "整理公司的差旅规则变化"}, config=config)
    request = waiting["clarification_request"]

    print("=== 超时默认项恢复 ===")
    print(f"clarification_request: {request}")
    result = await app.ainvoke(Command(resume=build_default_reply(request)), config=config)
    print(f"final_query: {result['final_query']}\n")


async def run_explicit_user_reply(app) -> None:
    config = {"configurable": {"thread_id": "clarify-user-demo"}}
    waiting = await app.ainvoke({"query": "整理公司的差旅规则变化"}, config=config)
    request = waiting["clarification_request"]

    print("=== 用户显式回复 ===")
    print(f"clarification_request: {request}")
    result = await app.ainvoke(
        Command(
            resume={
                "clarification_id": request["clarification_id"],
                "selected_option_id": "opt_30d",
                "answer_origin": "USER",
            }
        ),
        config=config,
    )
    print(f"final_query: {result['final_query']}\n")


async def main() -> None:
    saver = MemorySaver()
    graph = StateGraph(ClarifyState)
    graph.add_node("planner", planner)
    graph.add_node("wait", wait_for_clarify)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", route_after_planner, {"wait": "wait", "finalize": "finalize"})
    graph.add_conditional_edges("wait", route_after_wait, {"finalize": "finalize", "__end__": END})
    graph.add_edge("finalize", END)
    app = graph.compile(checkpointer=saver)

    await run_timeout_default(app)
    await run_explicit_user_reply(app)


if __name__ == "__main__":
    asyncio.run(main())
