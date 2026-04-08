"""
AgenticRAG SubtaskGraph 骨架（结果契约版）。

目标:
    演示 SubtaskGraph 的真实最小形态：
    - 有 `execution_id`
    - 有 `budget_slice`
    - 有 `evidence_ref`
    - 有 `COMPLETED / ESCALATED` 两类结果

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    见本文件导入、节点函数和构图代码

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/16_agentic_rag_patterns/02_subtask_graph_skeleton.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/16_agentic_rag_patterns/02_subtask_graph_skeleton.py

预期现象:
    运行后可观察本文件对应的状态推进、输出或集成行为

生产提醒:
    迁移到业务代码前，请结合 README / best_practices / pitfalls 一起阅读
"""
from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

try:
    from ...templates import EscalationReport, WorkerResultEnvelope
except ImportError:  # pragma: no cover
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import EscalationReport, WorkerResultEnvelope


class SubtaskState(TypedDict, total=False):
    task_id: int
    plan_version: int
    subtask_code: str
    execution_id: str
    task_type: Literal["RETRIEVAL", "REASONING"]
    query: str
    route_hints: list[str]
    budget_slice: dict
    evidence_ref: str | None
    eval_score: float
    gap_type: str
    next_action: Literal["complete", "escalate"]
    result_envelope: WorkerResultEnvelope | None


def prepare_node(state: SubtaskState) -> dict:
    print(
        "[prepare] "
        f"task_id={state['task_id']} plan_version={state['plan_version']} "
        f"subtask_code={state['subtask_code']} execution_id={state['execution_id']}"
    )
    print(f"[prepare] budget_slice={state.get('budget_slice')}")
    return {}


def retrieve_node(state: SubtaskState) -> dict:
    query = state.get("query", "")
    route_hints = state.get("route_hints", [])
    evidence_ref = f"evidence://{state['subtask_code']}/{state['execution_id']}"
    print(f"[retrieve] query={query}")
    print(f"[retrieve] route_hints={route_hints}")
    print(f"[retrieve] evidence_ref={evidence_ref}")
    return {"evidence_ref": evidence_ref}


def evaluate_node(state: SubtaskState) -> dict:
    query = state.get("query", "")
    if "时间范围不明确" in query:
        print("[evaluate] 发现 user_input_gap，需要上抛")
        return {"eval_score": 0.58, "gap_type": "user_input_gap", "next_action": "escalate"}
    print("[evaluate] 证据足够，准备 complete")
    return {"eval_score": 0.87, "gap_type": "none", "next_action": "complete"}


def complete_node(state: SubtaskState) -> dict:
    envelope: WorkerResultEnvelope = {
        "task_id": str(state["task_id"]),
        "execution_id": state["execution_id"],
        "worker_name": state["subtask_code"],
        "status": "COMPLETED",
        "summary": f"{state['subtask_code']} 完成，score={state['eval_score']}",
        "evidence_refs": [state["evidence_ref"]] if state.get("evidence_ref") else [],
        "output_ref": f"output://{state['subtask_code']}/{state['execution_id']}",
        "escalation": None,
    }
    print(f"[complete] result_envelope={envelope}")
    return {"result_envelope": envelope}


def escalate_node(state: SubtaskState) -> dict:
    escalation: EscalationReport = {
        "worker_name": state["subtask_code"],
        "reason": "needs_user_input",
        "gap_type": state["gap_type"],
        "message": "时间范围缺失，子图无法继续缩小检索范围",
        "suggested_global_action": "clarify",
        "best_score": state["eval_score"],
        "missing_slots": ["time_range"],
    }
    envelope: WorkerResultEnvelope = {
        "task_id": str(state["task_id"]),
        "execution_id": state["execution_id"],
        "worker_name": state["subtask_code"],
        "status": "ESCALATED",
        "summary": f"{state['subtask_code']} 上抛到 GlobalGraph",
        "evidence_refs": [state["evidence_ref"]] if state.get("evidence_ref") else [],
        "output_ref": None,
        "escalation": escalation,
    }
    print(f"[escalate] result_envelope={envelope}")
    return {"result_envelope": envelope}


def route_after_evaluate(state: SubtaskState) -> Literal["complete", "escalate"]:
    print(
        f"[route] eval_score={state.get('eval_score')} gap_type={state.get('gap_type')} "
        f"next_action={state.get('next_action')}"
    )
    return state.get("next_action", "escalate")


def build_subtask_graph():
    graph = StateGraph(SubtaskState)
    graph.add_node("prepare", prepare_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("complete", complete_node)
    graph.add_node("escalate", escalate_node)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "retrieve")
    graph.add_edge("retrieve", "evaluate")
    graph.add_conditional_edges("evaluate", route_after_evaluate, path_map={"complete": "complete", "escalate": "escalate"})
    graph.add_edge("complete", END)
    graph.add_edge("escalate", END)
    return graph.compile()


def get_langgraph_png(app: StateGraph, file_name: str) -> None:
    from pathlib import Path
    PARENT_DIR = Path(__file__).resolve().parent   # 获得当前文件的父目录
    FILE_PATH = str(PARENT_DIR / file_name)
    app.get_graph(xray=True).draw_mermaid_png(output_file_path=FILE_PATH)
    print(f"图已导出到 {FILE_PATH}")


if __name__ == "__main__":
    app = build_subtask_graph()

    get_langgraph_png(app, "02_subtask_graph_skeleton.png") # 画图 png
    
    print("=== 场景 1：正常完成 ===\n")
    completed = app.invoke(
        {
            "task_id": 1,
            "plan_version": 1,
            "subtask_code": "ST-001",
            "execution_id": "exec-001",
            "task_type": "RETRIEVAL",
            "query": "整理近 30 天差旅规则变化",
            "route_hints": ["vector", "search"],
            "budget_slice": {"llm_tokens": 2000, "retrieval_calls": 6},
        }
    )
    print(f"completed.result_envelope={completed['result_envelope']}\n")

    print("=== 场景 2：需要上抛 ===\n")
    escalated = app.invoke(
        {
            "task_id": 1,
            "plan_version": 1,
            "subtask_code": "ST-002",
            "execution_id": "exec-002",
            "task_type": "RETRIEVAL",
            "query": "时间范围不明确，需要整理差旅规则变化",
            "route_hints": ["vector", "search"],
            "budget_slice": {"llm_tokens": 2000, "retrieval_calls": 6},
        }
    )
    print(f"escalated.result_envelope={escalated['result_envelope']}")
