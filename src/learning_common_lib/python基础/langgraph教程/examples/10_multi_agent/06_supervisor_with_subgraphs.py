"""
10_multi_agent / 06_supervisor_with_subgraphs

目标:
    演示 Supervisor 选择“子图 worker”，而不是普通函数。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    StateGraph 嵌套、结构化 WorkerResultEnvelope

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/10_multi_agent/06_supervisor_with_subgraphs.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/10_multi_agent/06_supervisor_with_subgraphs.py

预期现象:
    1. Supervisor 先把任务派给 research 子图
    2. 再把结果交给 reviewer 子图
    3. reviewer 可返回 COMPLETED 或 ESCALATED

生产提醒:
    - 真正的 multi-agent 中，worker 更像“局部闭环子图”而不是一个裸函数
    - 父图只做控制面决策，子图只做本地任务闭环
"""
from __future__ import annotations

import asyncio
from typing import Literal, TypedDict

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.graph import END, START, StateGraph

try:
    from ...templates import WorkerResultEnvelope, WorkerTask
except ImportError:  # pragma: no cover
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import WorkerResultEnvelope, WorkerTask


class ResearchState(TypedDict, total=False):
    task: WorkerTask
    notes: list[str]
    result: WorkerResultEnvelope


class ReviewState(TypedDict, total=False):
    task: WorkerTask
    research_result: WorkerResultEnvelope
    result: WorkerResultEnvelope


class SupervisorState(TypedDict, total=False):
    query: str
    tasks: list[WorkerTask]
    task_cursor: int
    next_action: str
    current_task: WorkerTask
    latest_result: WorkerResultEnvelope | None
    collected_results: list[WorkerResultEnvelope]


def build_research_graph():
    def collect_notes(state: ResearchState) -> dict:
        objective = state["task"]["objective"]
        return {"notes": [f"检索到与「{objective}」相关的 2 条制度变更"]}

    def verify_notes(state: ResearchState) -> dict:
        task = state["task"]
        notes = state.get("notes", [])
        return {
            "result": {
                "task_id": task["task_id"],
                "execution_id": task["execution_id"],
                "worker_name": "researcher",
                "status": "COMPLETED",
                "summary": f"researcher 完成，产出 {len(notes)} 条笔记",
                "evidence_refs": ["EV-001", "EV-002"],
                "output_ref": "ref://research/001",
                "escalation": None,
            }
        }

    graph = StateGraph(ResearchState)
    graph.add_node("collect", collect_notes)
    graph.add_node("verify", verify_notes)
    graph.add_edge(START, "collect")
    graph.add_edge("collect", "verify")
    graph.add_edge("verify", END)
    return graph.compile()


def build_review_graph():
    def inspect_result(state: ReviewState) -> dict:
        summary = state["research_result"]["summary"]
        objective = state["task"]["objective"]
        if "时间范围" not in objective:
            return {
                "result": {
                    "task_id": state["task"]["task_id"],
                    "execution_id": state["task"]["execution_id"],
                    "worker_name": "reviewer",
                    "status": "ESCALATED",
                    "summary": "reviewer 发现缺口：没有明确时间范围",
                    "evidence_refs": [],
                    "output_ref": None,
                    "escalation": {
                        "worker_name": "reviewer",
                        "reason": "needs_user_input",
                        "gap_type": "clarification_gap",
                        "message": f"审核研究结果时发现缺口：{summary}",
                        "suggested_global_action": "clarify",
                        "best_score": 0.61,
                        "missing_slots": ["time_range"],
                    },
                }
            }
        return {
            "result": {
                "task_id": state["task"]["task_id"],
                "execution_id": state["task"]["execution_id"],
                "worker_name": "reviewer",
                "status": "COMPLETED",
                "summary": "reviewer 审核通过",
                "evidence_refs": [],
                "output_ref": "ref://review/001",
                "escalation": None,
            }
        }

    graph = StateGraph(ReviewState)
    graph.add_node("inspect", inspect_result)
    graph.add_edge(START, "inspect")
    graph.add_edge("inspect", END)
    return graph.compile()


async def main() -> None:
    research_graph = build_research_graph()
    review_graph = build_review_graph()
    llm = FakeListChatModel(
        responses=[
            '{"next_worker": "researcher"}',
            '{"next_worker": "reviewer"}',
            '{"next_worker": "FINISH"}',
        ]
    )

    async def choose_next(state: SupervisorState) -> dict:
        cursor = state.get("task_cursor", 0)
        tasks = state.get("tasks", [])
        if cursor >= len(tasks):
            return {"next_action": "__end__"}
        current = tasks[cursor]
        print(
            f"[supervisor] task_cursor={cursor} "
            f"current_task={current['task_id']} objective={current['objective']}"
        )
        chosen = llm.invoke(f"为当前任务选择 worker: {current['objective']}").content
        chosen = "researcher" if "researcher" in chosen else ("reviewer" if "reviewer" in chosen else "__end__")
        print(f"[supervisor] 第 {cursor + 1} 步 -> {chosen}")
        return {"current_task": current, "next_action": chosen}

    async def run_researcher(state: SupervisorState) -> dict:
        result = await research_graph.ainvoke({"task": state["current_task"], "notes": []})
        envelope = result["result"]
        print(f"[researcher] envelope={envelope}")
        return {
            "latest_result": envelope,
            "collected_results": [*state.get("collected_results", []), envelope],
            "task_cursor": state.get("task_cursor", 0) + 1,
        }

    async def run_reviewer(state: SupervisorState) -> dict:
        result = await review_graph.ainvoke(
            {
                "task": state["current_task"],
                "research_result": state["latest_result"],
            }
        )
        envelope = result["result"]
        print(f"[reviewer] input.latest_result={state.get('latest_result')}")
        print(f"[reviewer] envelope={envelope}")
        return {
            "latest_result": envelope,
            "collected_results": [*state.get("collected_results", []), envelope],
            "task_cursor": state.get("task_cursor", 0) + 1,
        }

    def route(state: SupervisorState) -> Literal["researcher", "reviewer", "__end__"]:
        return state.get("next_action", "__end__")

    graph = StateGraph(SupervisorState)
    graph.add_node("supervisor", choose_next)
    graph.add_node("researcher", run_researcher)
    graph.add_node("reviewer", run_reviewer)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route, {"researcher": "researcher", "reviewer": "reviewer", "__end__": END})  # 显示路由映射
    graph.add_edge("researcher", "supervisor")
    graph.add_edge("reviewer", "supervisor")
    app = graph.compile()

    get_langgraph_png(app, "06_supervisor_with_subgraphs.png")  # 导出图

    tasks: list[WorkerTask] = [
        {
            "task_id": "task-001",
            "plan_node_code": "NODE-001",
            "worker_name": "researcher",
            "objective": "搜集最近差旅制度变化",
            "context_ref": "ctx://001",
            "execution_id": "exec-001",
        },
        {
            "task_id": "task-002",
            "plan_node_code": "NODE-002",
            "worker_name": "reviewer",
            "objective": "审核结果是否缺少时间范围",
            "context_ref": "ctx://002",
            "execution_id": "exec-002",
        },
    ]
    result = await app.ainvoke(
        {
            "query": "整理企业差旅规则变化",
            "tasks": tasks,
            "task_cursor": 0,
            "collected_results": [],
        }
    )

    print("\n最终结果:")
    for item in result.get("collected_results", []):
        print(f"  - {item['worker_name']} [{item['status']}] {item['summary']}")
    print(f"  latest_result={result.get('latest_result')}")
    print(f"  task_cursor={result.get('task_cursor')}")


def get_langgraph_png(app: StateGraph, file_name: str) -> None:
    from pathlib import Path
    PARENT_DIR = Path(__file__).resolve().parent   # 获得当前文件的父目录
    FILE_PATH = str(PARENT_DIR / file_name)
    app.get_graph(xray=True).draw_mermaid_png(output_file_path=FILE_PATH)
    print(f"图已导出到 {FILE_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
