"""
解决什么问题: 提供 async-first 的 Celery 任务基类，统一生命周期回调（成功/失败/重试）、结构化日志、异常重试决策
输入输出约定: 继承 BaseTask 的 async def 任务自动获得 on_failure/on_retry/on_success 回调和结构化日志；
    任务体可通过 await self.safe_run(..., handler=...) 统一捕获异常并按策略重试；
    如果希望任务体直接抛出可重试异常并自动转成 self.retry()，请叠加 @async_autoretry(...)
失败策略: TaskRetryableError → 自动 self.retry()；TaskFatalError → 记录日志后放弃；
    未知异常 → 记录日志后放弃（保守策略，避免无限重试）
不适用场景: 不需要统一日志和重试策略的简单一次性任务

使用方式:
    @app.task(base=BaseTask, bind=True, max_retries=3)
    @async_autoretry(autoretry_for=(TaskRetryableError,))
    async def my_task(self, order_id: str) -> dict:
        ...
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from celery import Task

try:
    from .async_autoretry import async_autoretry
    from .error_handling import TaskError, TaskRetryableError, TaskFatalError, is_retryable
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.async_autoretry import async_autoretry  # type: ignore[no-redef]
    from templates.error_handling import (  # type: ignore[no-redef]
        TaskError, TaskRetryableError, TaskFatalError, is_retryable,
    )

logger = logging.getLogger(__name__)


class BaseTask(Task):
    """Celery 任务基类，提供统一的生命周期回调和结构化日志。"""

    # 默认重试参数（子任务可覆盖）。如果 async def 任务依赖“异常直接冒泡后自动重试”，
    # 仍需叠加 @async_autoretry(...)；Celery 内置 autoretry_for 无法捕获 await 期间抛出的异常。
    autoretry_for: tuple[type[Exception], ...] = (TaskRetryableError,)
    max_retries: int = 3
    default_retry_delay: int = 60  # 秒

    def _log_context(self, task_id: str | None = None) -> dict[str, Any]:
        """构建结构化日志上下文。"""
        return {
            "task_id": task_id or self.request.id,
            "task_name": self.name,
            "task_args": self.request.args,
            "task_kwargs": self.request.kwargs,
            "retries": self.request.retries,
        }

    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        """任务成功回调 — 记录结构化日志。"""
        ctx = self._log_context(task_id)
        logger.info("任务成功 ✅ task_id=%s task_name=%s retval=%s", ctx["task_id"], ctx["task_name"], retval, extra=ctx)

    def on_retry(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        """任务重试回调 — 记录异常和重试次数。"""
        ctx = self._log_context(task_id)
        logger.warning(
            "任务重试 🔄 task_id=%s task_name=%s retries=%s exc=%s",
            ctx["task_id"], ctx["task_name"], ctx["retries"], exc,
            extra=ctx,
        )

    def on_failure(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        """任务失败回调 — 记录异常详情。"""
        ctx = self._log_context(task_id)
        logger.error(
            "任务失败 ❌ task_id=%s task_name=%s exc=%r",
            ctx["task_id"], ctx["task_name"], exc,
            extra=ctx,
            exc_info=einfo,
        )

    async def safe_run(self, *args: Any, **kwargs: Any) -> Any:
        """统一异常捕获 + 重试决策的 async 执行入口。

        在 bind=True 的 async 任务中使用:
            @app.task(base=BaseTask, bind=True)
            async def my_task(self, order_id):
                return await self.safe_run(order_id, handler=_do_work)

        或者直接在任务体中 try/except 调用 self.retry_if_retryable(exc)。
        """
        handler = kwargs.pop("handler", None)
        if handler is None:
            raise TypeError("safe_run() 需要 handler 关键字参数")
        try:
            result = handler(*args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        except TaskRetryableError as exc:
            logger.warning("可重试异常，准备重试: %r", exc)
            raise self.retry(exc=exc)
        except TaskFatalError as exc:
            logger.error("不可重试异常，放弃任务: %r", exc)
            raise
        except Exception as exc:
            if is_retryable(exc):
                raise self.retry(exc=exc)
            logger.error("未知异常，放弃任务: %r", exc)
            raise

    def retry_if_retryable(self, exc: Exception) -> None:
        """根据异常类型决定是否重试。在任务体的 except 块中调用。"""
        if is_retryable(exc):
            raise self.retry(exc=exc)
        raise exc


# ---------------------------------------------------------------------------
# 异步结果获取
# ---------------------------------------------------------------------------


async def async_get_result(
    app_or_task_id: Any,
    task_id: str | None = None,
    timeout: float = 10.0,
) -> Any:
    """异步获取任务结果。

    用法:
        result = await async_get_result(app, task_id="xxx", timeout=5.0)
    或:
        result = await async_get_result("task-id-string", timeout=5.0)
    """
    from celery.result import AsyncResult

    if isinstance(app_or_task_id, str):
        tid = app_or_task_id
        async_result = AsyncResult(tid)
    else:
        tid = task_id
        if not tid:
            raise ValueError("传入 Celery App 时必须同时提供 task_id")
        async_result = AsyncResult(tid, app=app_or_task_id)

    return await asyncio.to_thread(async_result.get, timeout=timeout)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：展示 async-first BaseTask 的定义方式和结构。"""
    from celery import Celery

    try:
        from .celery_config import CeleryConfig
    except ImportError:
        from templates.celery_config import CeleryConfig  # type: ignore[no-redef]

    # 配置日志以便看到回调输出
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # 1. 创建 App（使用真实 Redis 配置）
    app = Celery("task_base_demo")
    app.config_from_object(CeleryConfig)
    print("🏭 创建 Celery App (CeleryConfig)")
    print(f"  broker_url: {app.conf.broker_url}")

    # 2. 定义使用 BaseTask 的 async 任务
    @app.task(base=BaseTask, bind=True, name="demo.process_order")
    async def process_order(self: BaseTask, order_id: str) -> dict:
        await asyncio.sleep(0.1)
        return {"order_id": order_id, "status": "completed"}

    print(f"\n📦 注册任务: {process_order.name}")
    print(f"  base class: {process_order.__class__.__name__}")
    print("  task 形态: async def")
    print(f"  max_retries: {process_order.max_retries}")
    print(f"  autoretry_for: {process_order.autoretry_for}")

    # 3. 定义带异常分类的 async 任务
    @app.task(base=BaseTask, bind=True, name="demo.risky_task", max_retries=2)
    @async_autoretry(autoretry_for=(TaskRetryableError,))
    async def risky_task(self: BaseTask, should_fail: str) -> str:
        await asyncio.sleep(0.05)
        if should_fail == "retryable":
            from templates.error_handling import ExternalServiceError
            raise ExternalServiceError("支付网关超时")
        elif should_fail == "fatal":
            raise TaskFatalError("数据格式损坏，无法修复")
        return "成功"

    print(f"\n📦 注册任务: {risky_task.name}")
    print(f"  max_retries: {risky_task.max_retries}")
    print("  retry mode: @async_autoretry + TaskRetryableError")

    # 4. 演示异常分类（不执行任务，仅展示分类逻辑）
    print("\n🎯 === 异常分类展示 ===")
    print(f"  TaskFatalError is_retryable: {is_retryable(TaskFatalError('test'))}")
    print(f"  TaskRetryableError is_retryable: {is_retryable(TaskRetryableError('test'))}")

    # 5. 演示 safe_run 模式（仅展示任务定义）
    print("\n🛡️ === safe_run 模式 ===")

    async def _do_work(item_id: str) -> dict:
        await asyncio.sleep(0.05)
        return {"item_id": item_id, "done": True}

    @app.task(base=BaseTask, bind=True, name="demo.safe_task")
    async def safe_task(self: BaseTask, item_id: str) -> dict:
        return await self.safe_run(item_id, handler=_do_work)

    print(f"  注册任务: {safe_task.name}")

    print("\n💡 async-first BaseTask 需要配合 custom aio pool worker 使用")
    print("   CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool' celery -A myproj.celery_app:app worker -P custom -Q aio_jobs --loglevel=info -c 20")

    print("\n✅ async-first BaseTask 演示完成")


if __name__ == "__main__":
    _demo()
