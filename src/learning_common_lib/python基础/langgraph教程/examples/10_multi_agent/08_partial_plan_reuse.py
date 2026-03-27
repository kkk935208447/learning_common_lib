from __future__ import annotations

"""
目标：演示 replan 时的部分结果复用。
关键 API：计划版本切换、completed task reuse
运行命令：python 08_partial_plan_reuse.py
预期现象：
  1. 第一版计划执行后发现缺口
  2. 第二版计划保留已完成节点，只补新节点
生产提醒：
  - replan 不是推倒重来
  - 要明确哪些节点可复用，哪些节点必须重跑
"""

import asyncio
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class ReuseState(TypedDict, total=False):
    plan_version: int
    plan: list[dict]
    completed_codes: list[str]
    reused_codes: list[str]
    next_action: str
    final_result: str


def planner(state: ReuseState) -> dict:
    version = state.get("plan_version", 0) + 1
    completed = set(state.get("completed_codes", []))

    if version == 1:
        plan = [
            {"code": "ST-001", "objective": "收集制度原文"},
            {"code": "ST-002", "objective": "汇总变化"},
        ]
    else:
        plan = [
            {"code": "ST-001", "objective": "收集制度原文"},
            {"code": "ST-003", "objective": "补充时间范围"},
            {"code": "ST-004", "objective": "重写近 30 天变化总结"},
        ]

    reused = [item["code"] for item in plan if item["code"] in completed]
    print(f"[planner] 生成 plan_version={version}, reused={reused}")
    print(f"[planner] plan={plan}")
    return {"plan_version": version, "plan": plan, "reused_codes": reused}


def executor(state: ReuseState) -> dict:
    completed = list(state.get("completed_codes", []))
    reused = set(state.get("reused_codes", []))
    print(f"[executor] completed(before)={completed}")
    for item in state.get("plan", []):
        code = item["code"]
        if code in reused:
            print(f"[executor] 复用 {code}，跳过执行")
            continue
        print(f"[executor] 执行 {code}: {item['objective']}")
        completed.append(code)

    if state["plan_version"] == 1:
        print(f"[executor] completed(after)={completed}")
        return {"completed_codes": completed, "next_action": "planner"}
    return {
        "completed_codes": completed,
        "next_action": "finalize",
        "final_result": f"最终完成节点: {completed}",
    }


def route(state: ReuseState):
    return state.get("next_action", "finalize")


async def main() -> None:
    graph = StateGraph(ReuseState)
    graph.add_node("planner", planner)
    graph.add_node("executor", executor)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")
    graph.add_conditional_edges("executor", route)
    graph.add_edge("finalize", END)
    graph.add_node("finalize", lambda state: {"final_result": state["final_result"]})
    app = graph.compile()

    result = await app.ainvoke({"completed_codes": [], "reused_codes": [], "plan_version": 0})
    print(f"\n{result['final_result']}")


if __name__ == "__main__":
    asyncio.run(main())
