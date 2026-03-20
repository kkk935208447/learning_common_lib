from __future__ import annotations

"""
目标: 双图架构 — GlobalGraph + SubtaskGraph，直接模拟 AgenticRAG 的双图设计
关键 API: StateGraph 嵌套、Command 跨图通信
运行命令: python 04_nested_dual_graph.py
预期现象: 全局图分解任务 → 子任务图逐个执行 → 全局图汇总结果，支持迭代重规划
生产提醒: 双图架构是复杂 Agent 系统的核心模式，注意控制全局迭代次数防止无限循环
"""

import asyncio
import operator
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------

class GlobalState(TypedDict, total=False):
    task_id: int
    original_query: str
    global_iteration: int
    max_iterations: int
    next_action: str
    subtask_results: Annotated[list[dict], operator.add]


# ---------------------------------------------------------------------------
# 子任务状态
# ---------------------------------------------------------------------------

class SubtaskState(TypedDict, total=False):
    subtask_code: str
    description: str
    iteration: int
    max_iterations: int
    next_action: str
    result: dict | None


# ---------------------------------------------------------------------------
# 子任务图节点
# ---------------------------------------------------------------------------

def subtask_execute(state: SubtaskState) -> dict:
    """执行子任务"""
    code = state.get("subtask_code", "unknown")
    desc = state.get("description", "")
    iteration = state.get("iteration", 0) + 1
    print(f"  [子任务 {code}] 第 {iteration} 次执行: {desc}")
    # 模拟执行结果
    success = iteration >= 2  # 第二次尝试成功
    return {
        "iteration": iteration,
        "result": {
            "code": code,
            "status": "success" if success else "retry",
            "detail": f"{desc} — {'完成' if success else '需重试'}",
        },
        "next_action": "done" if success else "retry",
    }


def subtask_route(state: SubtaskState) -> Literal["execute", "__end__"]:
    """子任务路由：重试或结束"""
    action = state.get("next_action", "done")
    max_iter = state.get("max_iterations", 3)
    if action == "retry" and state.get("iteration", 0) < max_iter:
        return "execute"
    return "__end__"


# 编译子任务图
sub_builder = StateGraph(SubtaskState)
sub_builder.add_node("execute", subtask_execute)
sub_builder.add_conditional_edges("execute", subtask_route)
sub_builder.add_edge(START, "execute")
subtask_graph = sub_builder.compile()


# ---------------------------------------------------------------------------
# 全局图节点
# ---------------------------------------------------------------------------

# 模拟任务分解计划
TASK_PLAN: list[dict] = [
    {"subtask_code": "S1", "description": "检索相关文档"},
    {"subtask_code": "S2", "description": "提取关键信息"},
    {"subtask_code": "S3", "description": "生成最终答案"},
]


def planner(state: GlobalState) -> dict:
    """全局规划器：分解任务"""
    iteration = state.get("global_iteration", 0) + 1
    print(f"\n[全局] 第 {iteration} 轮规划，query='{state.get('original_query', '')}'")
    return {"global_iteration": iteration, "next_action": "execute_subtasks"}


async def executor(state: GlobalState) -> dict:
    """全局执行器：依次运行子任务图"""
    results: list[dict] = []
    for task in TASK_PLAN:
        sub_input: SubtaskState = {
            "subtask_code": task["subtask_code"],
            "description": task["description"],
            "iteration": 0,
            "max_iterations": 3,
            "next_action": "execute",
        }
        sub_result = await subtask_graph.ainvoke(sub_input)
        if sub_result.get("result"):
            results.append(sub_result["result"])
    return {"subtask_results": results}


def evaluator(state: GlobalState) -> dict:
    """全局评估器：检查子任务结果质量"""
    results = state.get("subtask_results", [])
    all_success = all(r.get("status") == "success" for r in results)
    iteration = state.get("global_iteration", 0)
    max_iter = state.get("max_iterations", 2)

    if all_success or iteration >= max_iter:
        print(f"[全局] 评估通过，共 {len(results)} 个子任务完成")
        return {"next_action": "finish"}
    print(f"[全局] 评估未通过，触发重规划")
    return {"next_action": "replan"}


def global_route(state: GlobalState) -> Literal["planner", "__end__"]:
    """全局路由"""
    if state.get("next_action") == "replan":
        return "planner"
    return "__end__"


# ---------------------------------------------------------------------------
# 构建全局图
# ---------------------------------------------------------------------------

global_builder = StateGraph(GlobalState)
global_builder.add_node("planner", planner)
global_builder.add_node("executor", executor)
global_builder.add_node("evaluator", evaluator)

global_builder.add_edge(START, "planner")
global_builder.add_edge("planner", "executor")
global_builder.add_edge("executor", "evaluator")
global_builder.add_conditional_edges("evaluator", global_route)

global_graph = global_builder.compile()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    async def main() -> None:
        initial_state: GlobalState = {
            "task_id": 1,
            "original_query": "帮我分析 LangGraph 的双图架构",
            "global_iteration": 0,
            "max_iterations": 2,
            "next_action": "plan",
            "subtask_results": [],
        }
        result = await global_graph.ainvoke(initial_state)
        print(f"\n最终结果:")
        print(f"  全局迭代次数: {result.get('global_iteration')}")
        print(f"  子任务结果数: {len(result.get('subtask_results', []))}")
        for r in result.get("subtask_results", []):
            print(f"    - {r}")

    asyncio.run(main())
