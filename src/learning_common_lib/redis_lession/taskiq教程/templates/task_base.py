"""
解决什么问题: 提供任务装饰器工厂和通用任务包装器，统一日志格式、异常捕获、重试决策
输入输出约定: create_task() 装饰器工厂返回带标准 labels 的任务；safe_execute() 包装器统一异常处理
失败策略: safe_execute 捕获异常后通过 is_retryable() 分类，可重试异常 requeue，不可重试异常 reject
不适用场景: 简单任务无需包装，直接用 @broker.task 即可
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, TypeVar

try:
    from .error_handling import TaskError, TaskFatalError, TaskRetryableError, is_retryable
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.error_handling import TaskError, TaskFatalError, TaskRetryableError, is_retryable  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# 装饰器工厂
# ---------------------------------------------------------------------------


def create_task(
    broker: Any,
    *,
    queue: str = "default",
    max_retries: int = 3,
    retry_delay: float = 1.0,
    timeout: int = 300,
) -> Callable:
    """任务装饰器工厂，在 @broker.task 基础上注入标准 labels。

    参数:
        broker: TaskIQ Broker 实例
        queue: 队列名称，默认 "default"
        max_retries: 最大重试次数，默认 3
        retry_delay: 重试间隔（秒），默认 1.0
        timeout: 任务超时时间（秒），默认 300

    返回:
        装饰器，将被装饰函数注册为带标准 labels 的 TaskIQ 任务

    用法:
        @create_task(broker, queue="email", max_retries=5)
        async def send_email(to: str, subject: str, body: str) -> dict:
            ...
    """

    labels = {
        "queue": queue,
        "max_retries": str(max_retries),
        "retry_delay": str(retry_delay),
        "timeout": str(timeout),
    }

    def decorator(func: Callable) -> Any:
        """将函数注册为 TaskIQ 任务，并附加标准 labels。"""
        task = broker.task(
            task_name=func.__name__,
            **{k: v for k, v in labels.items()},
        )(func)
        # 保留原始 labels 供中间件读取
        task._task_labels = labels
        return task

    return decorator


# ---------------------------------------------------------------------------
# 通用任务包装器
# ---------------------------------------------------------------------------


async def safe_execute(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """统一的任务执行包装器，提供日志记录和异常分类。

    执行流程:
      1. 记录任务开始日志
      2. 调用目标协程 func(*args, **kwargs)
      3. 记录任务完成日志和耗时
      4. 异常分类处理:
         - TaskFatalError → 记录错误日志，直接 re-raise（不可重试）
         - TaskRetryableError → 记录警告日志，re-raise（由中间件决定重试）
         - Exception → 包装为 TaskError，记录错误日志后 re-raise

    参数:
        func: 要执行的异步函数
        *args: 位置参数
        **kwargs: 关键字参数

    返回:
        func 的返回值

    异常:
        TaskFatalError: 不可重试的致命错误
        TaskRetryableError: 可重试的临时错误
        TaskError: 其他未分类异常的包装
    """
    task_name = getattr(func, "__name__", repr(func))
    start = time.monotonic()
    logger.info("任务开始: %s | args=%s kwargs=%s", task_name, args, kwargs)

    try:
        result = await func(*args, **kwargs)
        elapsed = time.monotonic() - start
        logger.info("任务完成: %s | 耗时=%.3fs", task_name, elapsed)
        return result

    except TaskFatalError:
        elapsed = time.monotonic() - start
        logger.error(
            "任务致命错误（不可重试）: %s | 耗时=%.3fs", task_name, elapsed, exc_info=True,
        )
        raise

    except TaskRetryableError:
        elapsed = time.monotonic() - start
        logger.warning(
            "任务可重试错误: %s | 耗时=%.3fs", task_name, elapsed, exc_info=True,
        )
        raise

    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.error(
            "任务未知异常: %s | 耗时=%.3fs", task_name, elapsed, exc_info=True,
        )
        raise TaskError(f"任务 {task_name} 执行失败: {exc}") from exc


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：create_task 装饰器工厂和 safe_execute 包装器的使用方式。"""
    import asyncio

    print("=== create_task 装饰器工厂 ===")
    print("  用法示例:")
    print("    from templates.taskiq_app import init_broker")
    print("    broker = init_broker()")
    print()
    print("    @create_task(broker, queue='email', max_retries=5, timeout=60)")
    print("    async def send_email(to: str, subject: str) -> dict:")
    print("        return {'status': 'sent', 'to': to}")
    print()

    print("=== safe_execute 包装器 ===")
    print("  用法示例:")
    print("    async def my_task_logic(user_id: int) -> dict:")
    print("        return {'user_id': user_id, 'processed': True}")
    print()
    print("    result = await safe_execute(my_task_logic, user_id=42)")
    print()

    # 实际运行一个简单的 safe_execute 演示
    async def _run_demo() -> None:
        async def dummy_task(x: int) -> int:
            """模拟任务：返回 x * 2"""
            return x * 2

        result = await safe_execute(dummy_task, 21)
        print(f"  safe_execute(dummy_task, 21) = {result}")

        # 演示异常捕获
        async def failing_task() -> None:
            raise TaskRetryableError("模拟可重试错误")

        try:
            await safe_execute(failing_task)
        except TaskRetryableError as exc:
            print(f"  捕获到 TaskRetryableError: {exc}")

    asyncio.run(_run_demo())
    print()
    print("✅ task_base 模块演示完成")


if __name__ == "__main__":
    _demo()
