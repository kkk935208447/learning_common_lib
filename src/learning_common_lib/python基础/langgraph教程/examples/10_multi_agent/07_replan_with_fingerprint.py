"""
10_multi_agent / 07_replan_with_fingerprint

目标:
    演示结构化 planner + fingerprint + replan。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    Pydantic schema、FakeListChatModel、条件边循环

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/10_multi_agent/07_replan_with_fingerprint.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/10_multi_agent/07_replan_with_fingerprint.py

预期现象:
    1. planner 返回结构化计划而不是字符串列表
    2. evaluator 根据 gap_type 决定是否 replan
    3. fingerprint 防止“换汤不换药”的重复重规划

生产提醒:
    - replan 不应该只靠 iteration 计数
    - planner 输出最好是 schema 化，而不是自由文本
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Literal, TypedDict

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import BaseModel
from langgraph.graph import END, START, StateGraph


class StepModel(BaseModel):
    node_code: str                        
    worker_name: str                      # 执行者名称
    objective: str                        # 目标


class PlanModel(BaseModel):
    rationale: str                        # 计划理由
    steps: list[StepModel]                # 步骤列表


class ReplanState(TypedDict, total=False):
    query: str
    plan_json: str                        # 计划 JSON 字符串
    fingerprint: str                      # 指纹
    fingerprint_history: list[str]        # 指纹历史列表
    replan_count: int                     # 重规划次数
    max_replans: int                      # 最大重规划次数
    executed_steps: list[str]             # 已执行步骤列表
    gap_type: str                         # 缺口类型
    next_action: str                      # 下一步动作
    final_summary: str                    # 最终总结


def compute_fingerprint(plan: PlanModel) -> str:
    """ 
    计算规则：
    1. 提取 DAG 中所有子任务的 `(node_code, worker_name, objective)` 三元组。
    2. 按 `node_code` 字典序排序。
    3. 将排序后的三元组列表序列化为 JSON 字符串。
    4. 计算 SHA-256 哈希，取前 12 位作为指纹。
    """
    tuples = [
        (item.node_code, item.worker_name, item.objective)
        for item in plan.steps
    ]
    raw = json.dumps(sorted(tuples), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def planner_factory() -> FakeListChatModel:
    """ 
    返回一个 FakeListChatModel 实例，用于模拟 LLM 的响应。
    """
    return FakeListChatModel(
        responses=[
            json.dumps(
                {
                    "rationale": "先搜制度，再汇总变化",
                    "steps": [
                        {
                            "node_code": "NODE-001",
                            "worker_name": "researcher",
                            "objective": "搜集差旅制度变化",
                        },
                        {
                            "node_code": "NODE-002",
                            "worker_name": "writer",
                            "objective": "汇总已有变化点",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "rationale": "补上时间范围，再做最近窗口内汇总",
                    "steps": [
                        {
                            "node_code": "NODE-010",
                            "worker_name": "clarifier",
                            "objective": "补充最近 30 天时间范围",
                        },
                        {
                            "node_code": "NODE-011",
                            "worker_name": "researcher",
                            "objective": "搜集近 30 天差旅制度变化",
                        },
                        {
                            "node_code": "NODE-012",
                            "worker_name": "writer",
                            "objective": "汇总近 30 天变化点",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
        ]
    )


async def main() -> None:
    llm = planner_factory()

    def planner(state: ReplanState) -> dict:
        """ 
        规划器节点，负责生成计划，并计算指纹。
        """
        print(f"[planner] incoming_query={state['query']}")
        raw = llm.invoke(state["query"]).content
        plan = PlanModel.model_validate_json(raw)
        fingerprint = compute_fingerprint(plan)
        print(f"[planner] rationale={plan.rationale}")
        print(f"[planner] fingerprint={fingerprint}")
        print(f"[planner] steps={[step.model_dump() for step in plan.steps]}")
        return {
            "plan_json": plan.model_dump_json(ensure_ascii=False),
            "fingerprint": fingerprint,
        }

    def executor(state: ReplanState) -> dict:
        """ 
        执行器节点，负责执行计划。
        """
        plan = PlanModel.model_validate_json(state["plan_json"])
        executed = [f"{step.worker_name}:{step.objective}" for step in plan.steps]
        print("[executor]")
        for step in executed:
            print(f"  - {step}")
        return {"executed_steps": executed}

    def evaluator(state: ReplanState) -> dict:
        """ 
        评估器节点，负责评估计划是否需要重规划。
        """
        history = list(state.get("fingerprint_history", []))
        fingerprint = state["fingerprint"]
        replan_count = state.get("replan_count", 0)
        print(f"[evaluator] fingerprint_history(before)={history}")

        if fingerprint in history:
            print("[evaluator] 指纹重复，直接 fallback/finalize")
            return {"gap_type": "duplicate_plan", "next_action": "finalize"}

        history.append(fingerprint)
        if replan_count == 0:
            print("[evaluator] 第一轮缺少时间范围，触发 replan")
            next_query = f"{state['query']}（补充：近 30 天）"
            print(f"[evaluator] replanned_query={next_query}")
            return {
                "gap_type": "user_input_gap",
                "next_action": "planner",
                "fingerprint_history": history,
                "replan_count": replan_count + 1,
                "query": next_query,
            }

        print("[evaluator] 计划已足够，进入 finalize")
        return {
            "gap_type": "none",
            "next_action": "finalize",
            "fingerprint_history": history,
        }

    def finalize(state: ReplanState) -> dict:
        """ 
        最终节点，负责总结最终结果。
        """
        return {
            "final_summary": (
                f"最终 plan fingerprint={state['fingerprint']} "
                f"replans={state.get('replan_count', 0)} "
                f"steps={len(state.get('executed_steps', []))}"
            )
        }

    def route(state: ReplanState) -> Literal["planner", "finalize"]:
        return state.get("next_action", "finalize")

    graph = StateGraph(ReplanState)
    graph.add_node("planner", planner)
    graph.add_node("executor", executor)
    graph.add_node("evaluator", evaluator)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "evaluator")
    graph.add_conditional_edges("evaluator", route, {"planner": "planner", "finalize": "finalize"})
    graph.add_edge("finalize", END)
    app = graph.compile()

    get_langgraph_png(app, "07_replan_with_fingerprint.png")  # 导出图

    result = await app.ainvoke(
        {
            "query": "整理公司的差旅规则变化",
            "fingerprint_history": [],
            "replan_count": 0,
            "max_replans": 2,
            "executed_steps": [],
        }
    )
    print(f"\n{result['final_summary']}")


def get_langgraph_png(app: StateGraph, file_name: str) -> None:
    from pathlib import Path
    PARENT_DIR = Path(__file__).resolve().parent   # 获得当前文件的父目录
    FILE_PATH = str(PARENT_DIR / file_name)
    app.get_graph(xray=True).draw_mermaid_png(output_file_path=FILE_PATH)
    print(f"图已导出到 {FILE_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
