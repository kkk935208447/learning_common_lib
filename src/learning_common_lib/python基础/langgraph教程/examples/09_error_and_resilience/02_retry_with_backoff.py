from __future__ import annotations

"""
目标: 条件边重试 + 指数退避 + 最大重试次数，区分错误类型
关键 API: 条件边路由 + 状态中的重试计数器
运行命令: python 02_retry_with_backoff.py
预期现象: TRANSIENT 错误自动重试（指数退避），PERMANENT 错误直接失败，DEGRADABLE 降级处理
生产提醒: 区分错误类型是健壮系统的关键，避免对不可恢复错误做无意义重试
"""

import asyncio
import random
from enum import Enum
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph


# ---------------------------------------------------------------------------
# 错误类型
# ---------------------------------------------------------------------------

class ErrorType(str, Enum):
    TRANSIENT = "transient"      # 暂时性错误，可重试
    PERMANENT = "permanent"      # 永久性错误，不可恢复
    DEGRADABLE = "degradable"    # 可降级处理


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class State(TypedDict, total=False):
    task: str
    retry_count: int
    max_retries: int
    error_type: str
    error_msg: str
    result: str
    status: str  # "success" | "failed" | "degraded"


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------

def execute_task(state: State) -> dict:
    """执行任务，模拟不同类型的错误"""
    task = state.get("task", "")
    retry = state.get("retry_count", 0)
    print(f"[执行] task='{task}', retry={retry}")

    # 模拟：第 3 次重试成功
    if retry >= 2:
        print("[执行] 成功!")
        return {"result": f"任务完成: {task}", "status": "success", "error_type": ""}

    # 模拟随机错误类型
    error = random.choice([ErrorType.TRANSIENT, ErrorType.TRANSIENT, ErrorType.DEGRADABLE])
    print(f"[执行] 失败，错误类型: {error.value}")
    return {
        "error_type": error.value,
        "error_msg": f"模拟 {error.value} 错误",
        "retry_count": retry + 1,
    }


async def backoff_wait(state: State) -> dict:
    """指数退避等待"""
    retry = state.get("retry_count", 1)
    wait_time = min(2 ** retry * 0.1, 2.0)  # 0.2s, 0.4s, 0.8s... 最大 2s
    print(f"[退避] 等待 {wait_time:.1f}s (retry={retry})")
    await asyncio.sleep(wait_time)
    return {}


def degrade(state: State) -> dict:
    """降级处理"""
    print(f"[降级] 使用备选方案处理: {state.get('task', '')}")
    return {"result": f"降级结果: {state.get('task', '')}", "status": "degraded"}


def fail(state: State) -> dict:
    """永久失败"""
    print(f"[失败] 不可恢复: {state.get('error_msg', '')}")
    return {"result": f"失败: {state.get('error_msg', '')}", "status": "failed"}


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

def error_route(state: State) -> Literal["backoff", "degrade", "fail", "__end__"]:
    """根据错误类型和重试次数路由"""
    if state.get("status") == "success":
        return "__end__"

    error_type = state.get("error_type", "")
    retry = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if error_type == ErrorType.PERMANENT:
        return "fail"
    elif error_type == ErrorType.DEGRADABLE:
        return "degrade"
    elif error_type == ErrorType.TRANSIENT and retry < max_retries:
        return "backoff"
    return "fail"  # 超过最大重试次数


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------

builder = StateGraph(State)
builder.add_node("execute", execute_task)
builder.add_node("backoff", backoff_wait)
builder.add_node("degrade", degrade)
builder.add_node("fail", fail)

builder.add_edge(START, "execute")
builder.add_conditional_edges("execute", error_route)
builder.add_edge("backoff", "execute")  # 退避后重试
builder.add_edge("degrade", END)
builder.add_edge("fail", END)

graph = builder.compile()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

async def main() -> None:
    random.seed(42)
    result = await graph.ainvoke({
        "task": "调用外部 API",
        "retry_count": 0,
        "max_retries": 3,
    })
    print(f"\n最终结果: status={result.get('status')}, result={result.get('result')}")


if __name__ == "__main__":
    asyncio.run(main())
