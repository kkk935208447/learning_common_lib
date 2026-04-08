"""
16_agentic_rag_patterns / 05_networkx_plan_graph

目标:
    演示在 plan 节点内部使用 networkx 构建动态任务 DAG 计划图，
    再把 JSON-safe 的 DAG spec / topo layers 交给 LangGraph 执行。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    networkx.DiGraph
    networkx.is_directed_acyclic_graph
    networkx.topological_generations
    Send API

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/16_agentic_rag_patterns/05_networkx_plan_graph.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/16_agentic_rag_patterns/05_networkx_plan_graph.py

预期现象:
    1. plan 节点内部动态构建 networkx DAG
    2. plan 节点输出可序列化 dag_spec / topo_layers / dag_fingerprint
    3. dispatch 节点按 topo layer 分批 fan-out 到 worker
    4. 整个执行过程不把 networkx 对象放进 state/checkpoint

生产提醒:
    - networkx 在这里仅用于“计划图编译器”，不作为执行引擎
    - checkpoint / state 里只保留 JSON-safe dag_spec，不保留 DiGraph 对象
    - 如果后续要做 claim/retry/stale fencing，仍应依赖控制面状态和 execution_id
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import operator
from typing import Annotated, Any, TypedDict

import networkx as nx
from langgraph.graph import END, StateGraph
from langgraph.types import Send


class PlanDispatchState(TypedDict):
    query: str                                                # 用户查询
    dag_spec: dict[str, Any]                                  # 任务依赖图 nx.DiGraph 的 JSON-safe 规范
    dag_fingerprint: str                                      # 任务依赖图的指纹
    batch: int                                                # 当前批次
    layer_index: int                                          # 当前拓扑层级索引
    active_codes: list[str]                                   # 当前拓扑层级的活跃任务
    results: Annotated[list[str], operator.add]               # 当前批次的结果
    completed_codes: Annotated[list[str], operator.add]       # 已完成任务的代码列表


class WorkerInput(TypedDict):
    code: str                                                # 任务代码
    batch: int                                               # 当前批次
    kind: str                                                # 任务类型
    objective: str                                           # 任务目标


def build_dynamic_tasks(query: str) -> list[dict[str, Any]]:
    """根据用户查询动态生成任务定义。"""
    tasks = [
        {
            "code": "normalize_scope",
            "deps": [],
            "kind": "planner",
            "objective": f"规范化查询范围: {query}",
        },
        {
            "code": "retrieve_policy",
            "deps": ["normalize_scope"],
            "kind": "retrieval",
            "objective": "检索制度正文",
        },
        {
            "code": "retrieve_changelog",
            "deps": ["normalize_scope"],
            "kind": "retrieval",
            "objective": "检索变更记录",
        },
        {
            "code": "merge_evidence",
            "deps": ["retrieve_policy", "retrieve_changelog"],
            "kind": "analysis",
            "objective": "合并证据并抽取差异",
        },
        {
            "code": "write_answer",
            "deps": ["merge_evidence"],
            "kind": "generation",
            "objective": "撰写最终回答",
        },
    ]

    # 用一个很小的动态规则表示“计划图可以根据 query 变化”。
    if "报销" in query or "expense" in query.lower():
        tasks.insert(
            3,
            {
                "code": "retrieve_expense_faq",
                "deps": ["normalize_scope"],
                "kind": "retrieval",
                "objective": "检索报销 FAQ",
            },
        )
        for task in tasks:
            if task["code"] == "merge_evidence":
                task["deps"].append("retrieve_expense_faq")

    if "生产" in query or "上线" in query:
        tasks.insert(
            -1,
            {
                "code": "risk_review",
                "deps": ["merge_evidence"],
                "kind": "analysis",
                "objective": "补充生产风险复核",
            },
        )
        for task in tasks:
            if task["code"] == "write_answer":
                task["deps"] = ["risk_review"]

    return tasks


def compile_dag_spec(query: str) -> tuple[dict[str, Any], str]:
    """用 networkx 校验和编译 DAG，再降维为 JSON-safe spec。"""
    tasks = build_dynamic_tasks(query)
    graph = nx.DiGraph()

    for task in tasks:
        graph.add_node(
            task["code"],
            kind=task["kind"],
            objective=task["objective"],
        )
        for dep in task["deps"]:
            graph.add_edge(dep, task["code"])

    if not nx.is_directed_acyclic_graph(graph):
        raise ValueError("plan 节点产出的任务依赖图不是 DAG")
    # 获取拓扑层级，返回一个列表，每个元素是一个列表，表示一个拓扑层级
    topo_layers = [sorted(list(layer)) for layer in nx.topological_generations(graph)]
    # 构建 DAG spec，返回一个字典，包含 nodes、edges、topo_layers 三个字段，其中 nodes 是一个列表，每个元素是一个字典，表示一个节点，deps 是该节点的依赖节点列表，kind 是节点类型，objective 是节点目标
    dag_spec = {
        "nodes": [
            {
                "code": code,
                "deps": sorted(list(graph.predecessors(code))),
                "kind": graph.nodes[code]["kind"],
                "objective": graph.nodes[code]["objective"],
            }
            for code in sorted(graph.nodes)
        ],
        "edges": sorted([[src, dst] for src, dst in graph.edges]),
        "topo_layers": topo_layers,
    }
    dag_fingerprint = hashlib.sha256(
        json.dumps(dag_spec, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    return dag_spec, dag_fingerprint


def build_node_map(dag_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["code"]: node for node in dag_spec["nodes"]}


def build_networkx_plan_graph():
    def plan_node(state: PlanDispatchState) -> dict:
        query = state["query"]
        dag_spec, fingerprint = compile_dag_spec(query)
        print(f"[plan] query={query!r}")
        print(f"[plan] dag_fingerprint={fingerprint}")
        print(f"[plan] topo_layers={dag_spec['topo_layers']}")
        return {
            "dag_spec": dag_spec,
            "dag_fingerprint": fingerprint,
            "batch": 0,
            "layer_index": 0,
            "active_codes": [],
        }

    def dispatch_node(state: PlanDispatchState) -> dict:
        dag_spec = state["dag_spec"]
        layer_index = state.get("layer_index", 0)  # 当前拓扑层级索引
        batch = state.get("batch", 0) + 1            # 当前批次
        topo_layers = dag_spec["topo_layers"]        # 拓扑层级列表

        if layer_index >= len(topo_layers):            # 如果当前拓扑层级索引大于等于拓扑层级列表长度，则表示 DAG 已无剩余层
            print(f"[dispatch] 批次 {batch}: DAG 已无剩余层")    # 打印日志
            return {"batch": batch, "active_codes": []}

        active_codes = topo_layers[layer_index]        # 当前拓扑层级的活跃任务列表
        print(f"[dispatch] 批次 {batch}: 分发第 {layer_index} 层 {active_codes}")    # 打印日志
        return {"batch": batch, "active_codes": active_codes}

    def dispatch_route(state: PlanDispatchState) -> list[Send]:
        node_map = build_node_map(state["dag_spec"])    # 构建节点映射
        sends: list[Send] = []
        for code in state.get("active_codes", []):    # 遍历当前拓扑层级的活跃任务列表
            node = node_map[code]                    # 获取节点
            sends.append(
                Send(
                    "worker",                           # 发送给 worker 节点
                    {
                        "code": code,
                        "batch": state["batch"],        # 当前批次
                        "kind": node["kind"],            # 节点类型
                        "objective": node["objective"],  # 节点目标
                    },
                )                                        # 发送给 worker 节点
            )
        return sends

    def worker_node(state: WorkerInput) -> dict:
        code = state["code"]
        result = f"{code}@batch{state['batch']}::{state['kind']}"
        print(f"  [worker] {code} kind={state['kind']} objective={state['objective']}")
        return {"results": [result], "completed_codes": [code]}

    def gather_node(state: PlanDispatchState) -> dict:
        active_codes = state.get("active_codes", [])
        print(
            f"[gather] 本层完成 {len(active_codes)} 个节点, "
            f"累计完成 {len(state.get('completed_codes', []))} 个节点"
        )
        return {}

    def advance_layer_node(state: PlanDispatchState) -> dict:
        next_layer_index = state.get("layer_index", 0) + 1
        print(f"[advance] 进入下一层 layer_index={next_layer_index}")
        return {"layer_index": next_layer_index, "active_codes": []}

    def route_after_advance(state: PlanDispatchState) -> str:
        total_layers = len(state["dag_spec"]["topo_layers"])
        if state.get("layer_index", 0) >= total_layers:
            print("[check] 所有 topo layer 已完成")
            return "done"
        print("[check] 还有未完成 layer，继续 dispatch")
        return "dispatch"

    graph = StateGraph(PlanDispatchState)
    graph.add_node("plan", plan_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("worker", worker_node)
    graph.add_node("gather", gather_node)
    graph.add_node("advance", advance_layer_node)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "dispatch")
    graph.add_conditional_edges("dispatch", dispatch_route, ["worker"])
    graph.add_edge("worker", "gather")
    graph.add_edge("gather", "advance")
    graph.add_conditional_edges("advance", route_after_advance, {
        "dispatch": "dispatch",
        "done": END,
    })
    return graph.compile()


if __name__ == "__main__":
    async def main() -> None:
        print("=== networkx 计划图 -> LangGraph 执行 演示 ===\n")

        app = build_networkx_plan_graph()
        result = await app.ainvoke(
            {
                "query": "整理近 30 天差旅与报销规则变化，并考虑生产上线风险",
                "dag_spec": {},
                "dag_fingerprint": "",
                "batch": 0,
                "layer_index": 0,
                "active_codes": [],
                "results": [],
                "completed_codes": [],
            }
        )

        print(f"\ndag_fingerprint={result['dag_fingerprint']}")
        print(f"topo_layers={result['dag_spec']['topo_layers']}")
        print(f"completed_codes={result['completed_codes']}")
        print(f"results={result['results']}")

    asyncio.run(main())
