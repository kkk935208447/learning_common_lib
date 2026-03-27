"""
08_human_in_the_loop / 04_approval_workflow

目标:
    完整审批流 + Clarify 模式（toy baseline）

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    interrupt + Command(resume=...)

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/08_human_in_the_loop/04_approval_workflow.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/08_human_in_the_loop/04_approval_workflow.py

预期现象:
    请求进入审批流，审批者可批准/拒绝/要求澄清，澄清后重新提交

生产提醒:
    审批流是企业级 Agent 的核心模式，需要持久化 checkpointer 保证状态不丢失
"""
from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class ApprovalState(TypedDict, total=False):
    request: str
    clarification: str
    approval_status: str  # "pending" | "approved" | "rejected" | "needs_clarification"
    reviewer_comment: str
    final_result: str
    iteration: int


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------

def submit_request(state: ApprovalState) -> dict:
    """提交请求"""
    req = state.get("request", "")
    clarification = state.get("clarification", "")
    iteration = state.get("iteration", 0) + 1
    if clarification:
        print(f"[提交] 第 {iteration} 次提交（含澄清）: {req} | 澄清: {clarification}")
    else:
        print(f"[提交] 第 {iteration} 次提交: {req}")
    return {"approval_status": "pending", "iteration": iteration}


def review(state: ApprovalState) -> dict:
    """审核节点：中断等待人工审批"""
    req = state.get("request", "")
    clarification = state.get("clarification", "")
    prompt = f"请审核请求: '{req}'"
    if clarification:
        prompt += f"\n澄清信息: {clarification}"
    prompt += "\n请输入: approve / reject / clarify:原因"

    # 动态中断，等待审批者输入
    response = interrupt(prompt)
    response = str(response).strip()

    if response == "approve":
        return {"approval_status": "approved", "reviewer_comment": "审核通过"}
    elif response.startswith("clarify:"):
        reason = response[len("clarify:"):]
        return {
            "approval_status": "needs_clarification",
            "reviewer_comment": reason,
        }
    else:
        return {"approval_status": "rejected", "reviewer_comment": response}


def route_after_review(state: ApprovalState) -> Literal["clarify", "execute", "reject"]:
    """审核后路由"""
    status = state.get("approval_status", "")
    if status == "approved":
        return "execute"
    elif status == "needs_clarification":
        return "clarify"
    return "reject"


def clarify(state: ApprovalState) -> dict:
    """澄清节点：中断等待用户补充信息"""
    comment = state.get("reviewer_comment", "")
    print(f"[澄清] 审核者要求澄清: {comment}")
    user_input = interrupt(f"审核者要求澄清: {comment}\n请提供补充信息:")
    return {"clarification": str(user_input)}


def execute(state: ApprovalState) -> dict:
    """执行节点"""
    print(f"[执行] 请求已批准，执行: {state.get('request', '')}")
    return {"final_result": "执行成功"}


def reject(state: ApprovalState) -> dict:
    """拒绝节点"""
    comment = state.get("reviewer_comment", "")
    print(f"[拒绝] 请求被拒绝: {comment}")
    return {"final_result": f"已拒绝: {comment}"}


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------

builder = StateGraph(ApprovalState)
builder.add_node("submit", submit_request)
builder.add_node("review", review)
builder.add_node("clarify", clarify)
builder.add_node("execute", execute)
builder.add_node("reject", reject)

builder.add_edge(START, "submit")
builder.add_edge("submit", "review")
builder.add_conditional_edges("review", route_after_review)
builder.add_edge("clarify", "submit")  # 澄清后重新提交
builder.add_edge("execute", END)
builder.add_edge("reject", END)

memory = MemorySaver()
graph = builder.compile(checkpointer=memory)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    config = {"configurable": {"thread_id": "approval-1"}}

    # 提交请求 → 在 review 中断
    print("=== 提交请求 ===")
    result = graph.invoke({"request": "申请部署新版本到生产环境"}, config)
    print(f"等待审核... status={result.get('approval_status')}")

    # 审核者要求澄清
    print("\n=== 审核者要求澄清 ===")
    result = graph.invoke(Command(resume="clarify:请说明回滚方案"), config)
    print(f"需要澄清: {result.get('reviewer_comment')}")

    # 用户提供澄清
    print("\n=== 用户提供澄清 ===")
    result = graph.invoke(Command(resume="已准备自动回滚脚本"), config)
    print(f"等待再次审核... status={result.get('approval_status')}")

    # 审核者批准
    print("\n=== 审核者批准 ===")
    result = graph.invoke(Command(resume="approve"), config)
    print(f"最终结果: {result.get('final_result')}")
