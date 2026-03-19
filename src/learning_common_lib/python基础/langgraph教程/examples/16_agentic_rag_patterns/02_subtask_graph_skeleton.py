"""AgenticRAG SubtaskGraph 骨架

目标：
    演示 AgenticRAG 架构中 SubtaskGraph 的骨架设计，
    子任务图负责执行单个检索/处理子任务。

关键 API：
    - StateGraph + SubtaskState —— 子任务编排图
    - 子任务生命周期：init → retrieve → process → evaluate → complete

运行命令：
    python 02_subtask_graph_skeleton.py

预期现象：
    SubtaskGraph 执行单个子任务的完整生命周期，
    包括检索、处理、质量评估和结果输出。

生产提醒：
    - SubtaskGraph 由 GlobalGraph 的 scheduler 节点调度
    - 每个子任务应有超时控制和重试机制
    - 子任务结果需要回传给 GlobalGraph 进行聚合
"""
from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph


# ══════════════════════════════════════════════════════════
# SubtaskState 定义
# ══════════════════════════════════════════════════════════

class SubtaskState(TypedDict, total=False):
    """子任务状态"""
    subtask_id: str                 # 子任务 ID
    parent_task_id: int             # 父任务 ID（关联 GlobalState.task_id）
    subtask_type: Literal[          # 子任务类型
        "retrieval", "computation", "validation", "summarization"
    ]
    query: str                      # 子任务查询
    retrieved_docs: list[str]       # 检索到的文档
    processed_result: str           # 处理结果
    quality_score: float            # 质量评分 (0-1)
    status: Literal[                # 子任务状态
        "pending", "retrieving", "processing", "evaluating", "completed", "failed"
    ]
    retry_count: int                # 重试次数
    max_retries: int                # 最大重试次数
    error: str | None               # 错误信息


# ── 节点函数 ──────────────────────────────────────────────
def init_node(state: SubtaskState) -> dict:
    """初始化子任务"""
    subtask_id = state.get("subtask_id", "unknown")
    print(f"[init] 子任务 {subtask_id} 初始化，类型: {state.get('subtask_type', 'unknown')}")
    return {"status": "retrieving", "retry_count": 0}


def retrieve_node(state: SubtaskState) -> dict:
    """检索节点：从知识库检索相关文档"""
    query = state.get("query", "")

    print(f"[retrieve] 检索查询: {query}")

    # 模拟检索（生产环境替换为向量数据库调用）
    mock_docs = [
        f"文档1: 关于 {query} 的基础概念",
        f"文档2: {query} 的最佳实践",
        f"文档3: {query} 的常见问题",
    ]
    print(f"[retrieve] 检索到 {len(mock_docs)} 篇文档")
    return {"retrieved_docs": mock_docs, "status": "processing"}


def process_node(state: SubtaskState) -> dict:
    """处理节点：基于检索结果生成答案"""
    docs = state.get("retrieved_docs", [])
    subtask_type = state.get("subtask_type", "retrieval")

    print(f"[process] 处理 {len(docs)} 篇文档，类型: {subtask_type}")

    # 模拟不同类型的处理逻辑
    if subtask_type == "retrieval":
        result = f"基于 {len(docs)} 篇文档的检索结果摘要"
    elif subtask_type == "computation":
        result = f"计算结果: 基于 {len(docs)} 个数据源"
    elif subtask_type == "validation":
        result = f"验证结果: {len(docs)} 项检查通过"
    else:
        result = f"摘要: 综合 {len(docs)} 篇文档"

    return {"processed_result": result, "status": "evaluating"}


def evaluate_node(state: SubtaskState) -> dict:
    """评估节点：对处理结果进行质量评分"""
    result = state.get("processed_result", "")
    retry_count = state.get("retry_count", 0)

    # 模拟质量评估（生产环境用 LLM 评估）
    # 首次评估给较低分数以演示重试机制
    score = 0.6 if retry_count == 0 and "检索" in result else 0.85
    print(f"[evaluate] 质量评分: {score:.2f}（重试次数: {retry_count}）")

    return {"quality_score": score}


def route_after_evaluate(state: SubtaskState) -> str:
    """评估后路由：质量达标 → complete，否则 → retry 或 fail"""
    score = state.get("quality_score", 0)
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    if score >= 0.8:
        return "complete"
    elif retry_count < max_retries:
        print(f"[route] 质量不达标({score:.2f})，重试 ({retry_count + 1}/{max_retries})")
        return "retry"
    else:
        print(f"[route] 超过最大重试次数，标记失败")
        return "fail"


def retry_node(state: SubtaskState) -> dict:
    """重试节点：调整参数后重新检索"""
    retry_count = state.get("retry_count", 0) + 1
    query = state.get("query", "")
    # 模拟查询改写
    new_query = f"{query}（改写第{retry_count}次）"
    print(f"[retry] 改写查询: {new_query}")
    return {"retry_count": retry_count, "query": new_query, "status": "retrieving"}


def complete_node(state: SubtaskState) -> dict:
    """完成节点"""
    print(f"[complete] 子任务 {state.get('subtask_id')} 完成，"
          f"评分: {state.get('quality_score', 0):.2f}")
    return {"status": "completed"}


def fail_node(state: SubtaskState) -> dict:
    """失败节点"""
    print(f"[fail] 子任务 {state.get('subtask_id')} 失败")
    return {"status": "failed", "error": "质量评分未达标且超过最大重试次数"}


# ── 构建 SubtaskGraph ──────────────────────────────────
def build_subtask_graph():
    graph = StateGraph(SubtaskState)

    graph.add_node("init", init_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("process", process_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("retry", retry_node)
    graph.add_node("complete", complete_node)
    graph.add_node("fail", fail_node)

    graph.set_entry_point("init")
    graph.add_edge("init", "retrieve")
    graph.add_edge("retrieve", "process")
    graph.add_edge("process", "evaluate")
    graph.add_conditional_edges("evaluate", route_after_evaluate, {
        "complete": "complete",
        "retry": "retry",
        "fail": "fail",
    })
    graph.add_edge("retry", "retrieve")  # 重试回到检索
    graph.add_edge("complete", END)
    graph.add_edge("fail", END)

    return graph.compile()


if __name__ == "__main__":
    app = build_subtask_graph()

    print("=== AgenticRAG SubtaskGraph 骨架演示 ===\n")

    result = app.invoke({
        "subtask_id": "ST-001",
        "parent_task_id": 1,
        "subtask_type": "retrieval",
        "query": "LangGraph 记忆系统",
        "retrieved_docs": [],
        "processed_result": "",
        "quality_score": 0.0,
        "status": "pending",
        "retry_count": 0,
        "max_retries": 2,
        "error": None,
    })

    print(f"\n最终状态: status={result['status']}, score={result.get('quality_score', 0):.2f}")
