from __future__ import annotations

"""
目标: Plan-Execute-Replan 循环，直接模拟 AgenticRAG 全局循环
关键 API: planner→executor→evaluator→replan 四节点循环
运行命令: python 03_plan_execute_replan.py
预期现象: 规划器生成计划 → 执行器逐步执行 → 评估器检查质量 → 不满意则重规划
生产提醒: 控制最大迭代次数防止无限循环，每轮评估应有明确的通过/失败标准
"""

import asyncio
import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class PlanStep(TypedDict):
    step_id: int
    action: str
    status: str  # "pending" | "done" | "failed"


class State(TypedDict, total=False):
    query: str
    plan: list[PlanStep]
    current_step: int
    results: Annotated[list[str], operator.add]
    evaluation: str
    iteration: int
    max_iterations: int


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------

def planner(state: State) -> dict:
    """规划器：生成或更新执行计划"""
    query = state.get("query", "")
    iteration = state.get("iteration", 0) + 1
    print(f"\n[Planner] 第 {iteration} 轮规划, query='{query}'")

    if iteration == 1:
        plan = [
            {"step_id": 1, "action": "搜索相关资料", "status": "pending"},
            {"step_id": 2, "action": "分析关键信息", "status": "pending"},
            {"step_id": 3, "action": "生成回答", "status": "pending"},
        ]
    else:
        # 重规划：补充步骤
        plan = [
            {"step_id": 1, "action": "扩大搜索范围", "status": "pending"},
            {"step_id": 2, "action": "交叉验证信息", "status": "pending"},
            {"step_id": 3, "action": "重新生成回答", "status": "pending"},
        ]
    print(f"[Planner] 计划: {[s['action'] for s in plan]}")
    return {"plan": plan, "current_step": 0, "iteration": iteration}


def executor(state: State) -> dict:
    """执行器：逐步执行计划"""
    plan = state.get("plan", [])
    results: list[str] = []
    for step in plan:
        step["status"] = "done"
        result = f"[Step {step['step_id']}] {step['action']} → 完成"
        results.append(result)
        print(f"[Executor] {result}")
    return {"results": results, "plan": plan}


def evaluator(state: State) -> dict:
    """评估器：检查执行结果质量"""
    results = state.get("results", [])
    iteration = state.get("iteration", 0)
    # 模拟：第一轮不通过，第二轮通过
    passed = iteration >= 2
    evaluation = "pass" if passed else "needs_replan"
    print(f"[Evaluator] 结果数={len(results)}, 评估={evaluation}")
    return {"evaluation": evaluation}


def eval_route(state: State) -> Literal["planner", "__end__"]:
    """评估后路由"""
    if state.get("evaluation") == "needs_replan":
        max_iter = state.get("max_iterations", 3)
        if state.get("iteration", 0) < max_iter:
            return "planner"
    return "__end__"


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------

builder = StateGraph(State)
builder.add_node("planner", planner)
builder.add_node("executor", executor)
builder.add_node("evaluator", evaluator)

builder.add_edge(START, "planner")
builder.add_edge("planner", "executor")
builder.add_edge("executor", "evaluator")
builder.add_conditional_edges("evaluator", eval_route)

graph = builder.compile()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    async def main() -> None:
        result = await graph.ainvoke({
            "query": "LangGraph 的 Plan-Execute-Replan 模式",
            "results": [],
            "iteration": 0,
            "max_iterations": 3,
        })
        print(f"\n最终迭代次数: {result.get('iteration')}")
        print(f"评估结果: {result.get('evaluation')}")
        print(f"累计结果数: {len(result.get('results', []))}")

    asyncio.run(main())
