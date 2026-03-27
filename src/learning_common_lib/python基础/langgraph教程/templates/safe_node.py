"""节点错误处理中间件：为 LangGraph 节点提供统一的超时、异常捕获与降级能力。

注意：
- 当前版本最适合包装 `func(state)` 这种节点签名
- 如果节点还依赖 `RunnableConfig` / store / injected context，需要更高阶包装器
- 因此不要把这个示例模板误当成所有生产节点的最终通用解
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from enum import Enum
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 错误严重级别
# ---------------------------------------------------------------------------

class ErrorSeverity(Enum):
    """节点错误严重级别。"""

    TRANSIENT = "transient"      # 可重试（网络抖动等）
    PERMANENT = "permanent"      # 不可重试（业务逻辑错误）
    DEGRADABLE = "degradable"    # 可降级（非关键路径）


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class NodeError(Exception):
    """节点业务异常，携带严重级别信息。"""

    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.PERMANENT) -> None:
        self.severity = severity
        super().__init__(message)


# ---------------------------------------------------------------------------
# 装饰器
# ---------------------------------------------------------------------------

def safe_node(*, node_name: str, timeout_s: float = 30) -> Callable:
    """节点级统一错误处理装饰器。

    功能：
    - asyncio 超时保护
    - NodeError 业务异常捕获
    - 未知异常兜底
    - 所有异常均写入 state["error"] 并路由到 fallback
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            try:
                maybe_result = func(state)
                if inspect.isawaitable(maybe_result):
                    result = await asyncio.wait_for(maybe_result, timeout=timeout_s)
                else:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(func, state),
                        timeout=timeout_s,
                    )
                return result
            except asyncio.TimeoutError:
                logger.error("[%s] 超时 %ss", node_name, timeout_s)
                return {"error": f"{node_name}_timeout", "next_action": "fallback"}
            except NodeError as exc:
                logger.error(
                    "[%s] 业务错误: %s (severity=%s)",
                    node_name, exc, exc.severity.value,
                )
                return {"error": f"{node_name}: {exc}", "next_action": "fallback"}
            except Exception as exc:
                logger.exception("[%s] 未处理异常", node_name)
                return {
                    "error": f"{node_name}_error: {type(exc).__name__}",
                    "next_action": "fallback",
                }

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

async def _demo() -> None:
    """演示 safe_node 装饰器的基本用法。"""

    @safe_node(node_name="demo_node", timeout_s=5)
    async def my_node(state: dict[str, Any]) -> dict[str, Any]:
        print(f"  节点收到状态: {state}")
        return {"next_action": "continue"}

    # 正常执行
    result = await my_node({"messages": [], "iteration": 0})
    print(f"  正常结果: {result}")

    # 模拟超时
    @safe_node(node_name="slow_node", timeout_s=0.1)
    async def slow_node(state: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(10)
        return state

    result = await slow_node({"messages": []})
    print(f"  超时结果: {result}")

    # 模拟业务异常
    @safe_node(node_name="bad_node", timeout_s=5)
    async def bad_node(state: dict[str, Any]) -> dict[str, Any]:
        raise NodeError("数据格式错误", ErrorSeverity.PERMANENT)

    result = await bad_node({"messages": []})
    print(f"  异常结果: {result}")

    # 模拟同步节点
    @safe_node(node_name="sync_node", timeout_s=5)
    def sync_node(state: dict[str, Any]) -> dict[str, Any]:
        return {"next_action": "continue", "value": state.get("value", 0) + 1}

    result = await sync_node({"value": 1})
    print(f"  同步节点结果: {result}")


if __name__ == "__main__":
    asyncio.run(_demo())
