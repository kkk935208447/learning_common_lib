"""结构化日志 + 指标（可观测性）

目标：
    演示 LangGraph 生产环境的可观测性设计：
    五级 trace ID 体系、结构化日志、关键指标采集。

关键 API：
    - logging + structlog 风格 —— 结构化日志
    - 五级 trace ID（参考 AgenticRAG 可观测性设计）

运行命令：
    python 02_observability.py

预期现象：
    图执行过程中输出带有 trace ID 的结构化日志，
    执行完毕后输出性能指标汇总。

生产提醒：
    - 生产环境建议集成 LangSmith 或 OpenTelemetry
    - 日志级别：DEBUG(开发) / INFO(生产) / WARNING(告警)
    - 指标建议接入 Prometheus + Grafana 监控
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import TypedDict

from langgraph.graph import END, StateGraph

# ── 结构化日志配置 ──────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("langgraph.observability")


# ══════════════════════════════════════════════════════════
# 五级 Trace ID 体系
# ══════════════════════════════════════════════════════════
#
# L1: request_id   —— 用户请求级别（一次 API 调用）
# L2: session_id   —— 会话级别（多轮对话）
# L3: graph_run_id —— 图执行级别（一次 invoke）
# L4: node_run_id  —— 节点执行级别（单个节点）
# L5: llm_call_id  —— LLM 调用级别（单次模型调用）


class TraceContext:
    """Trace 上下文管理器"""

    def __init__(self, request_id: str | None = None, session_id: str | None = None):
        self.request_id = request_id or f"req-{uuid.uuid4().hex[:8]}"
        self.session_id = session_id or f"sess-{uuid.uuid4().hex[:8]}"
        self.graph_run_id = f"run-{uuid.uuid4().hex[:8]}"
        self.metrics: dict[str, list[float]] = {}
        self.start_time = time.monotonic()

    def new_node_id(self) -> str:
        return f"node-{uuid.uuid4().hex[:8]}"

    def log(self, level: str, message: str, **extra) -> None:
        """输出结构化日志"""
        log_data = {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "graph_run_id": self.graph_run_id,
            "msg": message,
            **extra,
        }
        log_str = json.dumps(log_data, ensure_ascii=False)
        getattr(logger, level)(log_str)

    def record_metric(self, name: str, value: float) -> None:
        """记录指标"""
        self.metrics.setdefault(name, []).append(value)

    def summary(self) -> dict:
        """生成指标汇总"""
        total_time = time.monotonic() - self.start_time
        result = {"total_time_ms": round(total_time * 1000, 2)}
        for name, values in self.metrics.items():
            result[f"{name}_count"] = len(values)
            result[f"{name}_avg_ms"] = round(sum(values) / len(values) * 1000, 2)
            result[f"{name}_total_ms"] = round(sum(values) * 1000, 2)
        return result


# ── 状态定义 ──────────────────────────────────────────────
class ObsState(TypedDict):
    query: str
    result: str
    trace_request_id: str


# ── 带可观测性的节点 ──────────────────────────────────────
# 全局 trace（生产环境应通过 config 传递）
trace: TraceContext | None = None


def observed_step1(state: ObsState) -> dict:
    """带观测的节点 1"""
    node_id = trace.new_node_id()
    start = time.monotonic()

    trace.log("info", "step1 开始", node_id=node_id, query=state["query"])

    # 模拟处理
    time.sleep(0.05)
    result = f"processed({state['query']})"

    elapsed = time.monotonic() - start
    trace.record_metric("node_latency", elapsed)
    trace.log("info", "step1 完成", node_id=node_id, latency_ms=round(elapsed * 1000, 2))

    return {"result": result}


def observed_step2(state: ObsState) -> dict:
    """带观测的节点 2"""
    node_id = trace.new_node_id()
    start = time.monotonic()

    trace.log("info", "step2 开始", node_id=node_id)

    # 模拟 LLM 调用
    llm_call_id = f"llm-{uuid.uuid4().hex[:8]}"
    trace.log("debug", "LLM 调用", node_id=node_id, llm_call_id=llm_call_id)
    time.sleep(0.1)  # 模拟延迟

    result = f"final({state['result']})"

    elapsed = time.monotonic() - start
    trace.record_metric("node_latency", elapsed)
    trace.record_metric("llm_latency", elapsed)
    trace.log("info", "step2 完成", node_id=node_id, latency_ms=round(elapsed * 1000, 2))

    return {"result": result}


# ── 构建图 ──────────────────────────────────────────────
def build_observed_graph():
    graph = StateGraph(ObsState)
    graph.add_node("step1", observed_step1)
    graph.add_node("step2", observed_step2)
    graph.set_entry_point("step1")
    graph.add_edge("step1", "step2")
    graph.add_edge("step2", END)
    return graph.compile()


if __name__ == "__main__":
    print("=== 可观测性演示 ===\n")

    # 创建 trace 上下文
    trace = TraceContext(request_id="req-demo-001", session_id="sess-demo-001")
    trace.log("info", "图执行开始")

    app = build_observed_graph()
    result = app.invoke({
        "query": "LangGraph 可观测性",
        "result": "",
        "trace_request_id": trace.request_id,
    })

    trace.log("info", "图执行完成", result=result["result"])

    # 输出指标汇总
    print(f"\n=== 指标汇总 ===")
    summary = trace.summary()
    for k, v in summary.items():
        print(f"  {k}: {v}")
