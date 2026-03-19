"""DAG 调度：READY 批次分发 + 结果回收

目标：
    演示 AgenticRAG 的 DAG 调度模式：
    compute_ready_codes 找出可执行节点 → claim 认领 → dispatch 分发 → 结果回收。

关键 API：
    - compute_ready_codes —— 计算 READY 状态的节点
    - claim —— 认领节点（防止重复执行）
    - Send API —— 并行分发 READY 节点

运行命令：
    python 04_dag_dispatch_pattern.py

预期现象：
    DAG 按拓扑顺序分批执行：先执行无依赖的节点，
    完成后解锁下游节点，直到所有节点完成。

生产提醒：
    - claim 操作需要原子性（生产环境用 Redis 分布式锁）
    - 每批 dispatch 后需要等待所有结果回收再计算下一批
    - DAG 指纹用于检测拓扑变化，避免重复执行
"""
from __future__ import annotations

import operator
from enum import Enum
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Send


# ══════════════════════════════════════════════════════════
# DAG 节点状态定义
# ══════════════════════════════════════════════════════════

class NodeStatus(str, Enum):
    PENDING = "pending"       # 等待依赖完成
    READY = "ready"           # 依赖已满足，可执行
    CLAIMED = "claimed"       # 已认领，执行中
    COMPLETED = "completed"   # 执行完成
    FAILED = "failed"         # 执行失败


class DAGNode:
    """DAG 中的单个节点"""
    def __init__(self, code: str, deps: list[str] | None = None):
        self.code = code
        self.deps = deps or []
        self.status = NodeStatus.PENDING
        self.result: str | None = None

    def __repr__(self) -> str:
        return f"DAGNode({self.code}, status={self.status.value})"


# ══════════════════════════════════════════════════════════
# DAG 调度器
# ══════════════════════════════════════════════════════════

class DAGScheduler:
    """DAG 调度器：管理节点状态和执行顺序"""

    def __init__(self, nodes: list[DAGNode]):
        self.nodes = {n.code: n for n in nodes}

    def compute_ready_codes(self) -> list[str]:
        """计算所有 READY 状态的节点

        规则：节点状态为 PENDING 且所有依赖已 COMPLETED
        """
        ready = []
        for code, node in self.nodes.items():
            if node.status != NodeStatus.PENDING:
                continue
            # 检查所有依赖是否已完成
            deps_met = all(
                self.nodes[dep].status == NodeStatus.COMPLETED
                for dep in node.deps
                if dep in self.nodes
            )
            if deps_met:
                ready.append(code)
        return ready

    def claim(self, code: str) -> bool:
        """认领节点（原子操作，防止重复执行）

        生产环境应使用 Redis 分布式锁实现原子性。
        """
        node = self.nodes.get(code)
        if node and node.status == NodeStatus.PENDING:
            node.status = NodeStatus.CLAIMED
            print(f"  [claim] 认领节点 {code}")
            return True
        # 已被认领或不存在
        return False

    def mark_ready(self) -> list[str]:
        """将可执行节点标记为 READY"""
        ready_codes = self.compute_ready_codes()
        for code in ready_codes:
            self.nodes[code].status = NodeStatus.READY
        return ready_codes

    def complete(self, code: str, result: str) -> None:
        """标记节点完成"""
        node = self.nodes.get(code)
        if node:
            node.status = NodeStatus.COMPLETED
            node.result = result
            print(f"  [complete] 节点 {code} 完成: {result}")

    def all_completed(self) -> bool:
        """检查是否所有节点都已完成"""
        return all(n.status == NodeStatus.COMPLETED for n in self.nodes.values())

    def summary(self) -> str:
        """输出 DAG 状态摘要"""
        lines = ["DAG 状态:"]
        for code, node in self.nodes.items():
            deps_str = f" (依赖: {', '.join(node.deps)})" if node.deps else ""
            lines.append(f"  {code}: {node.status.value}{deps_str}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# LangGraph 集成
# ══════════════════════════════════════════════════════════

class DispatchState(TypedDict):
    batch: int
    results: Annotated[list[str], operator.add]
    completed_codes: list[str]


class WorkerInput(TypedDict):
    code: str
    batch: int


# 全局调度器实例
scheduler: DAGScheduler | None = None


def dispatch_node(state: DispatchState) -> list[Send]:
    """计算 READY 节点并分发"""
    ready_codes = scheduler.compute_ready_codes()
    batch = state.get("batch", 0) + 1

    if not ready_codes:
        print(f"[dispatch] 批次 {batch}: 无可执行节点")
        return []

    print(f"[dispatch] 批次 {batch}: 分发 {len(ready_codes)} 个节点 {ready_codes}")

    # claim + dispatch
    sends = []
    for code in ready_codes:
        if scheduler.claim(code):
            sends.append(Send("worker", {"code": code, "batch": batch}))

    return sends


def worker_node(state: WorkerInput) -> dict:
    """执行单个 DAG 节点"""
    code = state["code"]
    # 模拟执行
    result = f"{code}_result"
    scheduler.complete(code, result)
    return {"results": [result]}


def check_and_continue(state: DispatchState) -> str:
    """检查是否所有节点完成"""
    if scheduler.all_completed():
        print("[check] 所有节点已完成")
        return "done"
    print("[check] 还有未完成节点，继续调度")
    return "dispatch"


def build_dag_dispatch_graph():
    graph = StateGraph(DispatchState)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("worker", worker_node)
    graph.add_node("check", lambda s: {})

    graph.set_entry_point("dispatch")
    graph.add_conditional_edges("dispatch", dispatch_node, ["worker"])
    graph.add_edge("worker", "check")
    graph.add_conditional_edges("check", check_and_continue, {
        "dispatch": "dispatch",
        "done": END,
    })
    return graph.compile()


if __name__ == "__main__":
    print("=== DAG 调度模式演示 ===\n")

    # 构建示例 DAG:
    #   A ──→ C ──→ E
    #   B ──→ C
    #   B ──→ D ──→ E
    dag_nodes = [
        DAGNode("A", deps=[]),
        DAGNode("B", deps=[]),
        DAGNode("C", deps=["A", "B"]),
        DAGNode("D", deps=["B"]),
        DAGNode("E", deps=["C", "D"]),
    ]
    scheduler = DAGScheduler(dag_nodes)

    print("初始 " + scheduler.summary())
    print()

    # 使用 LangGraph 执行 DAG 调度
    app = build_dag_dispatch_graph()
    result = app.invoke({"batch": 0, "results": [], "completed_codes": []})

    print(f"\n最终 {scheduler.summary()}")
    print(f"\n所有结果: {result['results']}")
