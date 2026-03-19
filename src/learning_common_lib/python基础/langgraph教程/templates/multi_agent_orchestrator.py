"""多 Agent 编排骨架：Supervisor + Worker 和 Plan-Execute-Replan 两种模式。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.graph import END, StateGraph

try:
    from .safe_node import safe_node
    from .state_schemas import AgentState
except ImportError:  # pragma: no cover - 允许直接运行模板文件
    from safe_node import safe_node
    from state_schemas import AgentState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker Agent
# ---------------------------------------------------------------------------

@dataclass
class WorkerAgent:
    """工作 Agent 定义。"""

    name: str
    description: str
    func: Callable
    timeout_s: float = 30.0


# ---------------------------------------------------------------------------
# Supervisor Agent
# ---------------------------------------------------------------------------

class SupervisorAgent:
    """Supervisor 模式：中心调度器将任务分发给 Worker。"""

    def __init__(self, workers: list[WorkerAgent], llm: Any | None = None) -> None:
        self._workers = {w.name: w for w in workers}
        self._llm = llm or FakeListChatModel(responses=["worker_a"])

    def build_graph(self) -> Any:
        """构建 Supervisor 模式的图。"""
        builder = StateGraph(AgentState)

        # 注册 supervisor 节点
        @safe_node(node_name="supervisor", timeout_s=30)
        async def supervisor_node(state: dict) -> dict:
            """Supervisor 决策：选择下一个 Worker 或结束。"""
            iteration = state.get("iteration", 0)
            max_iter = state.get("max_iterations", 5)
            if iteration >= max_iter:
                return {"next_action": "__end__"}
            # 简化：用 LLM 决定下一个 worker
            worker_names = list(self._workers.keys())
            response = self._llm.invoke(f"选择 worker: {worker_names}")
            chosen = response.content.strip()
            if chosen not in self._workers:
                chosen = worker_names[0]
            return {"next_action": chosen, "iteration": iteration + 1}

        builder.add_node("supervisor", supervisor_node)

        # 注册 worker 节点
        for name, worker in self._workers.items():
            wrapped = safe_node(node_name=name, timeout_s=worker.timeout_s)(worker.func)
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
    """演示 Supervisor 模式。"""

    async def worker_a_fn(state: dict) -> dict:
        print(f"  Worker A 执行, iteration={state.get('iteration', 0)}")
        return {"next_action": "supervisor"}

    async def worker_b_fn(state: dict) -> dict:
        print(f"  Worker B 执行, iteration={state.get('iteration', 0)}")
        return {"next_action": "supervisor"}

    workers = [
        WorkerAgent(name="worker_a", description="工作者A", func=worker_a_fn),
        WorkerAgent(name="worker_b", description="工作者B", func=worker_b_fn),
    ]

    llm = FakeListChatModel(responses=["worker_a", "worker_b", "worker_a"])
    supervisor = SupervisorAgent(workers, llm=llm)
    graph = supervisor.build_graph()

    result = await graph.ainvoke({"iteration": 0, "max_iterations": 3})
    print(f"  最终结果: {result}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_demo())
