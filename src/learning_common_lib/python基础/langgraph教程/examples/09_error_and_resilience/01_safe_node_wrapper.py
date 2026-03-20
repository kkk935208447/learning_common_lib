from __future__ import annotations

"""
目标: safe_node 装饰器 — 异常捕获 + 超时 + 结构化日志，参考 AgenticRAG 实现
关键 API: asyncio.wait_for, functools.wraps
运行命令: python 01_safe_node_wrapper.py
预期现象: 正常节点顺利执行，超时节点被捕获，异常节点被捕获，均不会导致图崩溃
生产提醒: 生产环境中每个节点都应包裹 safe_node，确保单节点故障不会导致整个图失败
"""

import asyncio
import logging
from functools import wraps
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

# ---------------------------------------------------------------------------
# safe_node 装饰器
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def safe_node(*, node_name: str, timeout_s: float = 30):
    """节点级统一错误处理装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(state: dict) -> dict:
            try:
                result = await asyncio.wait_for(func(state), timeout=timeout_s)
                logger.info(f"[{node_name}] 执行成功")
                return result
            except asyncio.TimeoutError:
                logger.error(f"[{node_name}] 超时 {timeout_s}s")
                return {
                    **state,
                    "error": f"{node_name}_timeout",
                    "next_action": "fallback",
                }
            except Exception as e:
                logger.exception(f"[{node_name}] 未处理异常")
                return {
                    **state,
                    "error": f"{node_name}_error: {type(e).__name__}",
                    "next_action": "fallback",
                }
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class State(TypedDict, total=False):
    data: str
    error: str
    next_action: str
    result: str


# ---------------------------------------------------------------------------
# 节点（使用 safe_node 装饰）
# ---------------------------------------------------------------------------

@safe_node(node_name="正常节点", timeout_s=5)
async def normal_node(state: dict) -> dict:
    """正常执行的节点"""
    print("[正常节点] 执行中...")
    await asyncio.sleep(0.1)
    return {"result": "正常完成", "next_action": "continue"}


@safe_node(node_name="超时节点", timeout_s=1)
async def timeout_node(state: dict) -> dict:
    """模拟超时的节点"""
    print("[超时节点] 开始执行（将超时）...")
    await asyncio.sleep(10)  # 超过 timeout_s
    return {"result": "不会到达这里"}


@safe_node(node_name="异常节点", timeout_s=5)
async def error_node(state: dict) -> dict:
    """模拟抛出异常的节点"""
    print("[异常节点] 执行中...")
    raise ValueError("模拟的业务异常")


def fallback_node(state: State) -> dict:
    """兜底节点"""
    error = state.get("error", "")
    print(f"[兜底] 处理错误: {error}")
    return {"result": f"降级处理: {error}", "next_action": "done"}


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------

def route(state: State) -> str:
    if state.get("next_action") == "fallback":
        return "fallback"
    return "__end__"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s - %(message)s")

    # 测试 1：正常节点
    print("=== 测试 1：正常节点 ===")
    b1 = StateGraph(State)
    b1.add_node("work", normal_node)
    b1.add_node("fallback", fallback_node)
    b1.add_edge(START, "work")
    b1.add_conditional_edges("work", route)
    b1.add_edge("fallback", END)
    g1 = b1.compile()
    r1 = await g1.ainvoke({"data": "test"})
    print(f"结果: {r1}\n")

    # 测试 2：超时节点
    print("=== 测试 2：超时节点 ===")
    b2 = StateGraph(State)
    b2.add_node("work", timeout_node)
    b2.add_node("fallback", fallback_node)
    b2.add_edge(START, "work")
    b2.add_conditional_edges("work", route)
    b2.add_edge("fallback", END)
    g2 = b2.compile()
    r2 = await g2.ainvoke({"data": "test"})
    print(f"结果: {r2}\n")

    # 测试 3：异常节点
    print("=== 测试 3：异常节点 ===")
    b3 = StateGraph(State)
    b3.add_node("work", error_node)
    b3.add_node("fallback", fallback_node)
    b3.add_edge(START, "work")
    b3.add_conditional_edges("work", route)
    b3.add_edge("fallback", END)
    g3 = b3.compile()
    r3 = await g3.ainvoke({"data": "test"})
    print(f"结果: {r3}")


if __name__ == "__main__":
    asyncio.run(main())
