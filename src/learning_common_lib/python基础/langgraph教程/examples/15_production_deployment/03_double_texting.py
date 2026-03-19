"""Double-texting 处理策略

目标：
    演示用户在 AI 处理过程中发送新消息（double-texting）的 4 种处理策略：
    enqueue / reject / interrupt / rollback。

关键 API：
    - interrupt 机制 —— 中断当前执行
    - checkpoint —— 状态回滚

运行命令：
    python 03_double_texting.py

预期现象：
    分别演示 4 种 double-texting 处理策略的行为差异。

生产提醒：
    - 选择策略取决于业务场景：聊天用 interrupt，表单用 reject
    - interrupt 需要 checkpointer 支持状态恢复
    - 生产环境建议在网关层实现，而非图内部
"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph


# ══════════════════════════════════════════════════════════
# Double-texting 策略定义
# ══════════════════════════════════════════════════════════

class Strategy(str, Enum):
    ENQUEUE = "enqueue"      # 排队：等当前完成后处理新消息
    REJECT = "reject"        # 拒绝：丢弃新消息，返回"请等待"
    INTERRUPT = "interrupt"  # 中断：停止当前任务，处理新消息
    ROLLBACK = "rollback"    # 回滚：撤销当前进度，从头处理新消息


STRATEGY_DESC = {
    Strategy.ENQUEUE: "排队等待 —— 当前任务完成后再处理新消息",
    Strategy.REJECT: "直接拒绝 —— 告知用户请等待当前任务完成",
    Strategy.INTERRUPT: "中断当前 —— 停止进行中的任务，转向新消息",
    Strategy.ROLLBACK: "回滚重来 —— 撤销当前进度，用新消息重新开始",
}


# ── 状态定义 ──────────────────────────────────────────────
class ChatState(TypedDict):
    query: str
    response: str
    processing: bool


# ── 模拟处理器 ──────────────────────────────────────────
class DoubleTextHandler:
    """Double-texting 处理器"""

    def __init__(self, strategy: Strategy):
        self.strategy = strategy
        self.is_processing = False
        self.queue: list[str] = []

    def handle_new_message(self, message: str) -> str:
        """处理新消息"""
        if not self.is_processing:
            return self._process(message)

        # 正在处理中，根据策略决定行为
        if self.strategy == Strategy.ENQUEUE:
            self.queue.append(message)
            return f"[enqueue] 消息已排队（队列长度: {len(self.queue)}）"

        elif self.strategy == Strategy.REJECT:
            return "[reject] 请等待当前任务完成后再发送"

        elif self.strategy == Strategy.INTERRUPT:
            print(f"  [interrupt] 中断当前任务，转向处理: {message}")
            self.is_processing = False
            return self._process(message)

        elif self.strategy == Strategy.ROLLBACK:
            print(f"  [rollback] 回滚当前进度，重新处理: {message}")
            self.is_processing = False
            return self._process(message)

        return "未知策略"

    def _process(self, message: str) -> str:
        """模拟处理消息"""
        self.is_processing = True
        time.sleep(0.1)  # 模拟处理延迟
        self.is_processing = False

        # 处理排队消息
        result = f"已处理: {message}"
        if self.queue:
            queued = self.queue.pop(0)
            result += f"\n  [enqueue] 继续处理排队消息: {queued}"

        return result


# ── 在 LangGraph 中实现 interrupt 策略 ──────────────────
def slow_node(state: ChatState) -> dict:
    """模拟耗时节点"""
    time.sleep(0.2)
    return {"response": f"处理完成: {state['query']}", "processing": False}


def build_interruptible_graph():
    """构建可中断的图"""
    graph = StateGraph(ChatState)
    graph.add_node("process", slow_node)
    graph.set_entry_point("process")
    graph.add_edge("process", END)
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


# ══════════════════════════════════════════════════════════
# 演示
# ══════════════════════════════════════════════════════════

def demo_strategy(strategy: Strategy) -> None:
    """演示单个策略"""
    print(f"\n策略: {strategy.value} —— {STRATEGY_DESC[strategy]}")
    handler = DoubleTextHandler(strategy)

    # 模拟：第一条消息正在处理时，第二条消息到达
    handler.is_processing = True  # 模拟正在处理
    result = handler.handle_new_message("第二条消息（double-text）")
    print(f"  结果: {result}")


if __name__ == "__main__":
    print("=== Double-Texting 处理策略 ===")

    for strategy in Strategy:
        demo_strategy(strategy)

    print("\n" + "=" * 50)
    print("\n=== LangGraph 可中断图演示 ===\n")

    app = build_interruptible_graph()
    config = {"configurable": {"thread_id": "dt-demo"}}

    result = app.invoke(
        {"query": "第一条消息", "response": "", "processing": True},
        config=config,
    )
    print(f"结果: {result['response']}")

    print("""
策略选择指南:
  - 聊天场景 → interrupt（用户改变意图，旧任务无意义）
  - 表单提交 → reject（防止重复提交）
  - 批处理   → enqueue（所有请求都需要处理）
  - 搜索场景 → rollback（用新关键词重新搜索）
""")
