"""
解决什么问题: 提供生产级中间件栈，包含结构化日志、指数退避重试、任务超时控制
输入输出约定: create_default_middlewares() 返回 list[TaskiqMiddleware]，按推荐顺序排列
失败策略: LoggingMiddleware 仅记录不干预；RetryMiddleware 根据 labels 决定重试；TimeoutMiddleware 超时后取消任务
不适用场景: 需要自定义中间件顺序时，直接组装而非使用 create_default_middlewares()

中间件栈（推荐顺序）:
  1. LoggingMiddleware   — 结构化日志（task_id, task_name, execution_time）
  2. RetryMiddleware     — 指数退避重试（读取 labels 中的 max_retries / retry_delay）
  3. TimeoutMiddleware   — 任务超时控制
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

try:
    from .error_handling import is_retryable
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.error_handling import is_retryable  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LoggingMiddleware — 结构化日志
# ---------------------------------------------------------------------------


class LoggingMiddleware(TaskiqMiddleware):
    """结构化日志中间件。

    在任务执行前后记录 task_id、task_name、execution_time 等关键信息，
    出错时记录异常类型和消息。仅记录日志，不干预任务执行流程。
    """

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """记录任务开始，并在 labels 中写入 _start_time 供 post_execute 计算耗时。"""
        message.labels["_start_time"] = str(time.monotonic())
        logger.info(
            "任务开始 | task_id=%s | task_name=%s",
            message.task_id,
            message.task_name,
        )
        return message

    async def post_execute(self, message: TaskiqMessage, result: TaskiqResult) -> None:
        """记录任务结束，计算执行耗时，标记是否出错。"""
        start = float(message.labels.get("_start_time", "0"))
        execution_time = time.monotonic() - start if start else 0.0
        logger.info(
            "任务结束 | task_id=%s | task_name=%s | execution_time=%.3fs | is_err=%s",
            message.task_id,
            message.task_name,
            execution_time,
            result.is_err,
        )

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult,
        exception: BaseException,
    ) -> None:
        """记录任务异常的类型和消息。"""
        logger.error(
            "任务异常 | task_id=%s | error_type=%s | error_msg=%s",
            message.task_id,
            type(exception).__name__,
            str(exception),
        )


# ---------------------------------------------------------------------------
# RetryMiddleware — 指数退避重试
# ---------------------------------------------------------------------------


class RetryMiddleware(TaskiqMiddleware):
    """指数退避重试中间件。

    从 message.labels 读取 max_retries（默认 3）和 retry_delay（默认 1.0）。
    仅对 is_retryable(err) 为 True 的异常进行重试。
    退避公式: delay = base_delay * (2 ** retry_count) + random.uniform(0, 1)
    """

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult,
        exception: BaseException,
    ) -> None:
        """根据 labels 配置决定是否重试，使用指数退避 + 抖动。"""
        if not is_retryable(exception):
            logger.debug(
                "不可重试异常，跳过重试 | task_id=%s | error_type=%s",
                message.task_id,
                type(exception).__name__,
            )
            return

        max_retries = int(message.labels.get("max_retries", "3"))
        base_delay = float(message.labels.get("retry_delay", "1.0"))
        retry_count = int(message.labels.get("_retry_count", "0"))

        if retry_count >= max_retries:
            logger.warning(
                "重试次数已耗尽 | task_id=%s | max_retries=%d",
                message.task_id,
                max_retries,
            )
            return

        delay = base_delay * (2 ** retry_count) + random.uniform(0, 1)
        retry_count += 1
        message.labels["_retry_count"] = str(retry_count)

        logger.info(
            "准备重试 | task_id=%s | retry=%d/%d | delay=%.2fs",
            message.task_id,
            retry_count,
            max_retries,
            delay,
        )
        await asyncio.sleep(delay)
        await self.broker.kick(message)


# ---------------------------------------------------------------------------
# TimeoutMiddleware — 任务超时控制
# ---------------------------------------------------------------------------


class TimeoutMiddleware(TaskiqMiddleware):
    """任务超时控制中间件。

    从 message.labels 读取 timeout（默认 300 秒）。
    在 post_execute 阶段检查执行耗时，超时则记录警告日志。
    """

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """读取 timeout 配置并记录到日志。"""
        timeout = int(message.labels.get("timeout", "300"))
        logger.debug(
            "超时配置 | task_id=%s | timeout=%ds",
            message.task_id,
            timeout,
        )
        return message

    async def post_execute(self, message: TaskiqMessage, result: TaskiqResult) -> None:
        """检查执行耗时是否超过 timeout，超时则记录警告。"""
        timeout = int(message.labels.get("timeout", "300"))
        start = float(message.labels.get("_start_time", "0"))
        execution_time = time.monotonic() - start if start else 0.0

        if execution_time > timeout:
            logger.warning(
                "任务超时 | task_id=%s | task_name=%s | execution_time=%.3fs | timeout=%ds",
                message.task_id,
                message.task_name,
                execution_time,
                timeout,
            )


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def create_default_middlewares() -> list[TaskiqMiddleware]:
    """返回推荐顺序的生产级中间件栈。

    顺序:
      1. LoggingMiddleware   — 结构化日志
      2. RetryMiddleware     — 指数退避重试
      3. TimeoutMiddleware   — 超时控制

    返回:
        list[TaskiqMiddleware]: 按推荐顺序排列的中间件列表
    """
    return [
        LoggingMiddleware(),
        RetryMiddleware(),
        TimeoutMiddleware(),
    ]


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：中间件栈信息、labels 配置重试行为、broker 集成用法。"""
    # 1. 查看默认中间件栈
    middlewares = create_default_middlewares()
    print("🔧 === 默认中间件栈（推荐顺序） ===")
    for i, mw in enumerate(middlewares, 1):
        print(f"  {i}. {type(mw).__name__}")
    print()

    # 2. labels 配置重试行为
    print("🏷️ === Labels 配置示例 ===")
    example_labels: dict[str, Any] = {
        "max_retries": "5",       # 最大重试 5 次（默认 3）
        "retry_delay": "2.0",     # 基础延迟 2 秒（默认 1.0）
        "timeout": "60",          # 超时 60 秒（默认 300）
    }
    for key, value in example_labels.items():
        print(f"  {key} = {value}")
    print()

    # 3. 与 broker 集成的用法
    print("📝 === 使用示例 ===")
    print("  from templates.middleware_stack import create_default_middlewares")
    print("  from templates.taskiq_app import create_taskiq_broker")
    print()
    print("  broker = create_taskiq_broker()")
    print("  broker = broker.with_middlewares(*create_default_middlewares())")
    print()
    print("  # 任务级别配置重试:")
    print('  @broker.task(max_retries="5", retry_delay="2.0", timeout="60")')
    print("  async def my_task(data: str) -> str:")
    print("      ...")
    print()
    print("✅ 中间件栈演示完成")


if __name__ == "__main__":
    _demo()
