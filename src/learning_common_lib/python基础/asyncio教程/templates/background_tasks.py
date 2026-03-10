"""
解决什么问题: 统一管理后台任务的注册、异常回收、日志记录和关闭时回收
输入输出约定: 通过 create() 注册任务，通过 shutdown() 统一取消和等待
失败策略: 任务异常自动记录日志，不会静默丢失
取消语义: shutdown() 会取消所有活跃任务并等待清理完成
不适用场景: 短生命周期并发任务，应使用 TaskGroup
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class BackgroundTaskManager:
    """后台任务的注册、异常回收和统一关闭。"""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    # ---- public API ----------------------------------------------------------

    def create(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        """创建后台任务并注册到管理器。"""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._done_callback)
        logger.info("background task created: %s", task.get_name())
        return task

    async def shutdown(self, timeout: float = 10.0) -> list[asyncio.Task[Any]]:
        """取消所有活跃任务并在 timeout 秒内等待它们完成。

        返回超时后仍未结束的任务列表（lingering tasks），调用方可决定如何处理。
        正常情况下返回空列表。
        """
        if not self._tasks:
            logger.info("no background tasks to shut down")
            return []

        active = [t for t in self._tasks if not t.done()]
        logger.info("shutting down %s background task(s)...", len(active))

        for task in active:
            task.cancel()

        lingering: list[asyncio.Task[Any]] = []
        try:
            async with asyncio.timeout(timeout):
                results = await asyncio.gather(*active, return_exceptions=True)
        except TimeoutError:
            lingering = [t for t in active if not t.done()]
            logger.warning(
                "shutdown timed out after %.1fs, %s task(s) still running: %s",
                timeout,
                len(lingering),
                [t.get_name() for t in lingering],
            )
            results = [
                t.exception() if t.done() and not t.cancelled() else asyncio.CancelledError()
                for t in active
                if t.done()
            ]

        cancelled = sum(1 for r in results if isinstance(r, asyncio.CancelledError))
        errors = sum(
            1 for r in results
            if isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError)
        )
        logger.info(
            "shutdown complete: cancelled=%s errors=%s lingering=%s",
            cancelled, errors, len(lingering),
        )
        # 只清除已完成的任务，保留 lingering 任务的引用
        self._tasks = set(lingering)
        return lingering

    def __len__(self) -> int:
        return len(self._tasks)

    # ---- internal ------------------------------------------------------------

    def _done_callback(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            logger.debug("background task cancelled: %s", task.get_name())
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "background task %s failed: %s", task.get_name(), exc, exc_info=exc
            )


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

async def _worker(n: int) -> None:
    """模拟一个长时间运行的后台任务。"""
    logger.info("worker-%s started", n)
    try:
        await asyncio.sleep(100)
    except asyncio.CancelledError:
        logger.info("worker-%s cancelled", n)
        raise


async def _demo() -> None:
    mgr = BackgroundTaskManager()
    for i in range(3):
        mgr.create(_worker(i), name=f"worker-{i}")

    logger.info("active tasks: %s", len(mgr))
    await asyncio.sleep(1)
    await mgr.shutdown()
    logger.info("active tasks after shutdown: %s", len(mgr))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    asyncio.run(_demo())
