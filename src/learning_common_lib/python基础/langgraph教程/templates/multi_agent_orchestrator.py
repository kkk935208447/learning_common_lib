"""
多 Agent 编排骨架：Supervisor + Graph Worker 和 Plan-Execute-Replan。

目标:
    多 Agent 编排骨架：Supervisor + Graph Worker 和 Plan-Execute-Replan。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    见本文件导入、节点函数和构图代码

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: templates/multi_agent_orchestrator.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python templates/multi_agent_orchestrator.py

预期现象:
    运行后可观察本文件对应的状态推进、输出或集成行为

生产提醒:
    迁移到业务代码前，请结合 README / best_practices / pitfalls 一起阅读
"""
from __future__ import annotations

import json
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable, Literal, TypedDict

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.graph import END, StateGraph

try:
    from .safe_node import safe_node
    from .state_schemas import AgentState
    from .teaching_contracts import EscalationReport, WorkerResultEnvelope, WorkerTask
except ImportError:  # pragma: no cover - 允许直接运行模板文件
    from safe_node import safe_node
    from state_schemas import AgentState
    from teaching_contracts import EscalationReport, WorkerResultEnvelope, WorkerTask

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker Agent
# ---------------------------------------------------------------------------

@dataclass
class WorkerAgent:
    """工作 Agent 定义。

    `func` 适合 toy baseline，`graph` 适合真实版 graph-as-agent 教学。
    """

    name: str
    description: str
    func: Callable | None = None
    graph: Any | None = None
    input_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    timeout_s: float = 30.0


class SupervisorState(AgentState, total=False):
    query: str
    planned_tasks: list[WorkerTask]
    current_task: WorkerTask | None
    worker_results: list[WorkerResultEnvelope]


def _coerce_worker_result(
    worker: WorkerAgent,
    task: WorkerTask,
    result: dict[str, Any],
) -> WorkerResultEnvelope:
    """把子图/函数结果归一成统一 envelope。"""
    if {"task_id", "execution_id", "worker_name", "status"} <= result.keys():
        return result  # 已经是 envelope 形状

    escalation: EscalationReport | None = result.get("escalation")
    status: Literal["COMPLETED", "ESCALATED", "STALE_IGNORED"] = (
        "ESCALATED" if escalation else "COMPLETED"
    )
    summary = result.get("summary") or result.get("result") or f"{worker.name} 完成任务"
    return {
        "task_id": task.get("task_id", ""),
        "execution_id": task.get("execution_id", ""),
        "worker_name": worker.name,
        "status": status,
        "summary": str(summary),
        "evidence_refs": list(result.get("evidence_refs", [])),
        "output_ref": result.get("output_ref"),
        "escalation": escalation,
    }


# ---------------------------------------------------------------------------
# Supervisor Agent
# ---------------------------------------------------------------------------

class SupervisorAgent:
    """Supervisor 模式：中心调度器将任务分发给 Worker。"""

    def __init__(self, workers: list[WorkerAgent], llm: Any | None = None) -> None:
        self._workers = {w.name: w for w in workers}
        self._llm = llm or FakeListChatModel(responses=['{"next_worker":"worker_a"}'])

    def _choose_worker(self, state: SupervisorState) -> str:
        planned_tasks = state.get("planned_tasks", [])
        completed = {item["task_id"] for item in state.get("worker_results", [])}
        current_task = next(
            (task for task in planned_tasks if task.get("task_id") not in completed),
            None,
        )
        if current_task is not None:
            return current_task["worker_name"]

        worker_names = sorted(self._workers.keys())
        response = self._llm.invoke(
            json.dumps(
                {
                    "query": state.get("query", ""),
                    "workers": worker_names,
                    "instruction": "返回 JSON: {\"next_worker\": \"...\"} 或 {\"next_worker\": \"FINISH\"}",
                },
                ensure_ascii=False,
            )
        ).content.strip()
        try:
            payload = json.loads(response)
            chosen = payload.get("next_worker", "FINISH")
        except json.JSONDecodeError:
            chosen = response
        return chosen if chosen in self._workers else "__end__"

    def build_graph(self) -> Any:
        """构建 Supervisor 模式的图。"""
        builder = StateGraph(SupervisorState)

        # 注册 supervisor 节点
        @safe_node(node_name="supervisor", timeout_s=30)
        async def supervisor_node(state: SupervisorState) -> dict:
            """Supervisor 决策：选择下一个 Worker 或结束。"""
            iteration = state.get("iteration", 0)
            max_iter = state.get("max_iterations", 5)
            if iteration >= max_iter:
                return {"next_action": "__end__"}
            planned_tasks = list(state.get("planned_tasks", []))
            if not planned_tasks and state.get("query"):
                planned_tasks = [
                    {
                        "task_id": f"task-{iteration + 1}",
                        "plan_node_code": f"NODE-{iteration + 1:03d}",
                        "worker_name": self._choose_worker(state),
                        "objective": state.get("query", ""),
                        "context_ref": None,
                        "execution_id": f"exec-{iteration + 1:03d}",
                    }
                ]

            chosen = self._choose_worker({**state, "planned_tasks": planned_tasks})
            if chosen == "__end__":
                return {"next_action": "__end__", "planned_tasks": planned_tasks}

            current_task = next(
                (
                    task for task in planned_tasks
                    if task.get("worker_name") == chosen
                    and task.get("task_id")
                    not in {item["task_id"] for item in state.get("worker_results", [])}
                ),
                None,
            )
            return {
                "next_action": chosen,
                "planned_tasks": planned_tasks,
                "current_task": current_task,
                "iteration": iteration + 1,
            }

        builder.add_node("supervisor", supervisor_node)

        # 注册 worker 节点
        for name, worker in self._workers.items():
            if worker.func is None and worker.graph is None:
                raise ValueError(f"worker={name} 既没有 func 也没有 graph")

            async def run_worker(
                state: SupervisorState,
                *,
                _worker: WorkerAgent = worker,
            ) -> dict[str, Any]:
                task = state.get("current_task")
                if task is None:
                    return {"next_action": "__end__"}
                worker_input = _worker.input_builder(state) if _worker.input_builder else dict(state)
                if _worker.graph is not None:
                    result = await _worker.graph.ainvoke(worker_input)
                else:
                    maybe_result = _worker.func(worker_input)
                    if inspect.isawaitable(maybe_result):
                        result = await maybe_result
                    else:
                        result = maybe_result
                envelope = _coerce_worker_result(_worker, task, result)
                return {
                    "worker_results": [*state.get("worker_results", []), envelope],
                    "next_action": "supervisor",
                    "current_task": None,
                }

            wrapped = safe_node(node_name=name, timeout_s=worker.timeout_s)(run_worker)
            builder.add_node(name, wrapped)
            builder.add_edge(name, "supervisor")

        # 条件路由
        def route(state: dict) -> str:
            return state.get("next_action", "__end__")

        mapping = {w: w for w in self._workers}
        mapping["__end__"] = END
        builder.add_conditional_edges("supervisor", route, mapping)
        builder.set_entry_point("supervisor")
        return builder.compile()


# ---------------------------------------------------------------------------
# Orchestrator（Plan-Execute-Replan）
# ---------------------------------------------------------------------------

class Orchestrator:
    """Plan-Execute-Replan 编排器骨架。"""

    def __init__(self, planner_fn: Callable, executor_fn: Callable, llm: Any | None = None) -> None:
        self._planner = planner_fn
        self._executor = executor_fn
        self._llm = llm or FakeListChatModel(responses=["done"])

    def build_graph(self) -> Any:
        """构建 Plan-Execute-Replan 模式的图。"""
        builder = StateGraph(AgentState)

        @safe_node(node_name="planner", timeout_s=30)
        async def plan_node(state: dict) -> dict:
            return await self._planner(state)

        @safe_node(node_name="executor", timeout_s=60)
        async def execute_node(state: dict) -> dict:
            return await self._executor(state)

        @safe_node(node_name="replanner", timeout_s=30)
        async def replan_node(state: dict) -> dict:
            """判断是否需要重新规划。"""
            iteration = state.get("iteration", 0)
            max_iter = state.get("max_iterations", 3)
            if iteration >= max_iter:
                return {"next_action": "__end__"}
            response = self._llm.invoke("是否需要重新规划？")
            if "done" in response.content.lower():
                return {"next_action": "__end__"}
            return {"next_action": "planner", "iteration": iteration + 1}

        builder.add_node("planner", plan_node)
        builder.add_node("executor", execute_node)
        builder.add_node("replanner", replan_node)

        builder.add_edge("planner", "executor")
        builder.add_edge("executor", "replanner")

        def replan_route(state: dict) -> str:
            return state.get("next_action", "__end__")

        builder.add_conditional_edges("replanner", replan_route, {
            "planner": "planner",
            "__end__": END,
        })
        builder.set_entry_point("planner")
        return builder.compile()


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

async def _demo() -> None:
    """演示 Supervisor + graph worker 模式。"""

    class GraphWorkerState(TypedDict, total=False):
        objective: str
        notes: list[str]
        summary: str

    async def researcher_prepare(state: GraphWorkerState) -> dict:
        objective = state.get("objective", "")
        return {"notes": [f"检索资料: {objective}"]}

    async def researcher_verify(state: GraphWorkerState) -> dict:
        note_count = len(state.get("notes", []))
        return {"summary": f"researcher 完成，产出 {note_count} 条笔记"}

    researcher_graph = StateGraph(GraphWorkerState)
    researcher_graph.add_node("prepare", researcher_prepare)
    researcher_graph.add_node("verify", researcher_verify)
    researcher_graph.set_entry_point("prepare")
    researcher_graph.add_edge("prepare", "verify")
    researcher_graph.add_edge("verify", END)
    compiled_researcher = researcher_graph.compile()

    async def worker_a_fn(state: dict) -> dict:
        task = state.get("current_task", {})
        return {"summary": f"worker_a 执行: {task.get('objective', '')}"}

    async def worker_b_fn(state: dict) -> dict:
        task = state.get("current_task", {})
        return {
            "summary": f"worker_b 发现缺口: {task.get('objective', '')}",
            "escalation": {
                "worker_name": "worker_b",
                "reason": "needs_user_input",
                "gap_type": "clarification_gap",
                "message": "需要更精确的时间范围",
                "suggested_global_action": "clarify",
                "best_score": 0.58,
                "missing_slots": ["time_range"],
            },
        }

    workers = [
        WorkerAgent(
            name="worker_a",
            description="research graph worker",
            graph=compiled_researcher,
            input_builder=lambda state: {"objective": state["current_task"]["objective"], "notes": [], "summary": ""},
        ),
        WorkerAgent(name="worker_b", description="工作者B", func=worker_b_fn),
    ]

    llm = FakeListChatModel(
        responses=[
            '{"next_worker":"worker_a"}',
            '{"next_worker":"worker_b"}',
            '{"next_worker":"FINISH"}',
        ]
    )
    supervisor = SupervisorAgent(workers, llm=llm)
    graph = supervisor.build_graph()

    result = await graph.ainvoke(
        {
            "query": "整理最近一周的差旅规则变更",
            "planned_tasks": [
                {
                    "task_id": "task-1",
                    "plan_node_code": "NODE-001",
                    "worker_name": "worker_a",
                    "objective": "先搜集制度变更信息",
                    "context_ref": "ctx://task-1",
                    "execution_id": "exec-001",
                },
                {
                    "task_id": "task-2",
                    "plan_node_code": "NODE-002",
                    "worker_name": "worker_b",
                    "objective": "检查是否还需要用户补充时间范围",
                    "context_ref": "ctx://task-2",
                    "execution_id": "exec-002",
                },
            ],
            "worker_results": [],
            "iteration": 0,
            "max_iterations": 4,
        }
    )
    print("  worker_results:")
    for item in result.get("worker_results", []):
        print(f"    - {item['worker_name']} [{item['status']}] {item['summary']}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_demo())
