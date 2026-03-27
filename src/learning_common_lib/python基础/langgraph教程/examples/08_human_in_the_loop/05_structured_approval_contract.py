"""
08_human_in_the_loop / 05_structured_approval_contract

目标:
    演示结构化审批契约，而不是自由字符串 resume。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    interrupt + Command(resume={...})

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/08_human_in_the_loop/05_structured_approval_contract.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/08_human_in_the_loop/05_structured_approval_contract.py

预期现象:
    1. 图产出结构化审批请求
    2. 审批人提交结构化 decision
    3. 图根据结构化字段路由到 execute / reject

生产提醒:
    - 企业审批流应该恢复“结构化决策”，而不是 `approve` 这种裸字符串
    - 审批请求至少要带 approval_id / expires_at / reviewer_role
"""
from __future__ import annotations

import asyncio
from typing import Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class ApprovalDecision(TypedDict):
    approval_id: str
    decision: Literal["APPROVED", "REJECTED"]
    reviewer: str
    comment: str


class ApprovalState(TypedDict, total=False):
    request: str
    approval_request: dict
    approval_decision: ApprovalDecision | None
    final_result: str


def submit(state: ApprovalState) -> dict:
    request = state.get("request", "")
    approval_request = {
        "approval_id": "approval-001",
        "question": f"是否批准请求：{request}",
        "reviewer_role": "ops_lead",
        "expires_at": "2026-03-26T12:30:00Z",
        "options": ["APPROVED", "REJECTED"],
    }
    print(f"[submit] 生成结构化审批请求: {approval_request}")
    return {"approval_request": approval_request}


def review(state: ApprovalState) -> dict:
    decision = interrupt(state["approval_request"])
    if not isinstance(decision, dict):
        raise ValueError("审批恢复必须是结构化 dict，而不是裸字符串")
    if decision.get("approval_id") != state["approval_request"]["approval_id"]:
        raise ValueError("approval_id 不匹配，拒绝恢复")
    print(f"[review] 收到审批决定: {decision}")
    return {"approval_decision": decision}


def route_after_review(state: ApprovalState) -> Literal["execute", "reject"]:
    if state.get("approval_decision", {}).get("decision") == "APPROVED":
        return "execute"
    return "reject"


def execute(state: ApprovalState) -> dict:
    decision = state["approval_decision"]
    return {"final_result": f"执行成功，审批人={decision['reviewer']} comment={decision['comment']}"}


def reject(state: ApprovalState) -> dict:
    decision = state["approval_decision"]
    return {"final_result": f"请求已拒绝，审批人={decision['reviewer']} comment={decision['comment']}"}


async def main() -> None:
    saver = MemorySaver()
    graph = StateGraph(ApprovalState)
    graph.add_node("submit", submit)
    graph.add_node("review", review)
    graph.add_node("execute", execute)
    graph.add_node("reject", reject)
    graph.add_edge(START, "submit")
    graph.add_edge("submit", "review")
    graph.add_conditional_edges("review", route_after_review)
    graph.add_edge("execute", END)
    graph.add_edge("reject", END)
    app = graph.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "approval-structured-demo"}}
    print("=== 进入等待态 ===")
    waiting = await app.ainvoke({"request": "部署新的知识库索引"}, config=config)
    print(waiting["approval_request"])

    print("\n=== 审批恢复 ===")
    result = await app.ainvoke(
        Command(
            resume={
                "approval_id": "approval-001",
                "decision": "APPROVED",
                "reviewer": "ops.lead",
                "comment": "窗口期已确认",
            }
        ),
        config=config,
    )
    print(result["final_result"])


if __name__ == "__main__":
    asyncio.run(main())
