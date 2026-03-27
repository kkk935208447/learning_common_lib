"""
结构化日志 + 指标（async-safe 观测版）。

目标:
    演示 LangGraph 生产环境中更真实的可观测性设计：
    - trace 上下文通过 config 传递，而不是全局变量
    - 节点内只用 async-safe 等待，不阻塞事件循环
    - 打印 request/session/run/node 四级关键标识

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    见本文件导入、节点函数和构图代码

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/15_production_deployment/02_observability.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/15_production_deployment/02_observability.py

预期现象:
    运行后可观察本文件对应的状态推进、输出或集成行为

生产提醒:
    迁移到业务代码前，请结合 README / best_practices / pitfalls 一起阅读
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("langgraph.observability")


METRICS: dict[str, list[float]] = {"node_latency": [], "llm_latency": []}


class ObsState(TypedDict, total=False):
    query: str
    normalized_query: str
    result: str


def log_event(message: str, **extra) -> None:
    logger.info(json.dumps({"msg": message, **extra}, ensure_ascii=False))


async def observed_step1(state: ObsState, config: RunnableConfig) -> dict:
    cfg = config.get("configurable", {})
    node_run_id = f"node-{uuid.uuid4().hex[:8]}"
    start = time.monotonic()
    log_event(
        "step1_start",
        request_id=cfg.get("request_id"),
        session_id=cfg.get("session_id"),
        graph_run_id=cfg.get("graph_run_id"),
        node_run_id=node_run_id,
        query=state.get("query"),
    )
    await asyncio.sleep(0.03)
    normalized = state.get("query", "").strip().lower()
    elapsed = time.monotonic() - start
    METRICS["node_latency"].append(elapsed)
    log_event(
        "step1_done",
        request_id=cfg.get("request_id"),
        graph_run_id=cfg.get("graph_run_id"),
        node_run_id=node_run_id,
        latency_ms=round(elapsed * 1000, 2),
        normalized_query=normalized,
    )
    return {"normalized_query": normalized}


async def observed_step2(state: ObsState, config: RunnableConfig) -> dict:
    cfg = config.get("configurable", {})
    node_run_id = f"node-{uuid.uuid4().hex[:8]}"
    llm_call_id = f"llm-{uuid.uuid4().hex[:8]}"
    start = time.monotonic()
    log_event(
        "step2_start",
        request_id=cfg.get("request_id"),
        graph_run_id=cfg.get("graph_run_id"),
        node_run_id=node_run_id,
        llm_call_id=llm_call_id,
    )
    await asyncio.sleep(0.05)
    result = f"final({state.get('normalized_query', '')})"
    elapsed = time.monotonic() - start
    METRICS["node_latency"].append(elapsed)
    METRICS["llm_latency"].append(elapsed)
    log_event(
        "step2_done",
        request_id=cfg.get("request_id"),
        graph_run_id=cfg.get("graph_run_id"),
        node_run_id=node_run_id,
        llm_call_id=llm_call_id,
        latency_ms=round(elapsed * 1000, 2),
        result=result,
    )
    return {"result": result}


def metric_summary() -> dict[str, float]:
    return {
        "node_latency_count": len(METRICS["node_latency"]),
        "node_latency_avg_ms": round(sum(METRICS["node_latency"]) / len(METRICS["node_latency"]) * 1000, 2),
        "llm_latency_count": len(METRICS["llm_latency"]),
        "llm_latency_avg_ms": round(sum(METRICS["llm_latency"]) / len(METRICS["llm_latency"]) * 1000, 2),
    }


async def main() -> None:
    METRICS["node_latency"].clear()
    METRICS["llm_latency"].clear()

    graph = StateGraph(ObsState)
    graph.add_node("step1", observed_step1)
    graph.add_node("step2", observed_step2)
    graph.add_edge(START, "step1")
    graph.add_edge("step1", "step2")
    graph.add_edge("step2", END)
    app = graph.compile()

    config = {
        "configurable": {
            "request_id": "req-demo-001",
            "session_id": "sess-demo-001",
            "graph_run_id": f"run-{uuid.uuid4().hex[:8]}",
        }
    }
    result = await app.ainvoke({"query": "LangGraph 可观测性"}, config=config)
    print("\n=== 指标汇总 ===")
    print(metric_summary())
    print("=== 最终结果 ===")
    print(result["result"])


if __name__ == "__main__":
    asyncio.run(main())
