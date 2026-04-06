"""
并行执行后聚合结果（Map-Reduce 聚合）

目标:
    演示 Send + reducer 实现完整的 map-reduce 模式：
    分发多个并行任务 → 各自独立处理 → 结果自动聚合 → 最终汇总。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    - Send(node, state) —— 路由函数中动态分发
    - add_conditional_edges(...) —— 将准备好的任务 fan-out 到 worker
    - Annotated[list, operator.add] —— reducer 自动聚合

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/11_dynamic_and_parallel/04_map_reduce_aggregation.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/11_dynamic_and_parallel/04_map_reduce_aggregation.py

预期现象:
    3 个文档并行分析，各自生成摘要，最终聚合为一份综合报告。

生产提醒:
    - reducer 的选择决定聚合行为：operator.add 适合列表拼接
    - 如果 worker 可能失败，建议在 worker 内部 try-except 并返回错误标记
    - 大规模并行时注意内存占用，可分批 dispatch
"""
from __future__ import annotations

import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Send


# ── 状态定义 ──────────────────────────────────────────────
class DocState(TypedDict):
    """单个文档的处理状态"""
    doc_id: str                                            # 文档 ID
    content: str


class MainState(TypedDict):
    """主状态：documents 待处理，summaries 通过 reducer 聚合"""
    documents: list[dict[str, str]]                         # 待处理文档列表
    dispatch_docs: list[dict[str, str]]                     # 已分发文档列表
    batch: int                                              # 批次号
    summaries: Annotated[list[dict], operator.add]          # 多个 worker 的结果自动合并
    final_report: str                                       # 最终报告


# ── 节点函数 ──────────────────────────────────────────────
def dispatch_node(state: MainState) -> dict:
    """准备一批要 fan-out 的文档。"""
    docs = list(state["documents"])
    batch = state.get("batch", 0) + 1
    print(f"[dispatch] 第 {batch} 批分发 {len(docs)} 个文档到并行 worker")
    return {"dispatch_docs": docs, "batch": batch}


def dispatch_route(state: MainState) -> list[Send]:
    """基于 dispatch_docs fan-out 到 analyze_worker。"""
    return [
        Send("analyze_worker", {"doc_id": doc["id"], "content": doc["content"]})
        for doc in state.get("dispatch_docs", [])
    ]


def analyze_worker(state: DocState) -> dict:
    """模拟文档分析 worker（生产环境替换为 LLM 调用）"""
    doc_id = state["doc_id"]
    content = state["content"]
    # 模拟分析：提取关键词 + 生成摘要
    word_count = len(content)
    summary = {
        "doc_id": doc_id,
        "word_count": word_count,
        "summary": f"文档 {doc_id} 包含 {word_count} 字，主题: {content[:20]}...",
        "status": "success",
    }
    print(f"  [worker-{doc_id}] 分析完成: {word_count} 字")
    return {"summaries": [summary]}


def aggregate_node(state: MainState) -> dict:
    """聚合所有 worker 的结果，生成最终报告"""
    summaries = state["summaries"]
    total_docs = len(summaries)
    total_words = sum(s["word_count"] for s in summaries)
    success_count = sum(1 for s in summaries if s["status"] == "success")

    report = (
        f"=== 聚合报告 ===\n"
        f"处理文档数: {total_docs}\n"
        f"成功数: {success_count}\n"
        f"总字数: {total_words}\n"
        f"各文档摘要:\n"
    )
    for s in summaries:
        report += f"  - {s['summary']}\n"

    print(f"[aggregate] 生成报告: {total_docs} 个文档, {total_words} 总字数")
    return {"final_report": report}


# ── 构建图 ──────────────────────────────────────────────
def build_map_reduce_graph() -> StateGraph:
    graph = StateGraph(MainState)

    graph.add_node("dispatch", dispatch_node)
    graph.add_node("analyze_worker", analyze_worker)
    graph.add_node("aggregate", aggregate_node)

    graph.set_entry_point("dispatch")
    graph.add_conditional_edges("dispatch", dispatch_route, ["analyze_worker"])
    graph.add_edge("analyze_worker", "aggregate")
    graph.add_edge("aggregate", END)

    return graph.compile()


if __name__ == "__main__":
    async def main() -> None:
        app = build_map_reduce_graph()

        documents = [
            {"id": "DOC-001", "content": "LangGraph 是一个用于构建有状态多步骤 AI 应用的框架"},
            {"id": "DOC-002", "content": "Celery 是 Python 生态中最流行的分布式任务队列"},
            {"id": "DOC-003", "content": "Redis 既可以作为缓存也可以作为消息代理使用"},
        ]

        print("=== Map-Reduce 聚合演示 ===\n")
        result = await app.ainvoke({
            "documents": documents,
            "dispatch_docs": [],
            "batch": 0,
            "summaries": [],
            "final_report": "",
        })

        print(f"\n{result['final_report']}")

    asyncio.run(main())
