"""
解决什么问题: 提供跨平台的优雅关闭模板，处理信号注册和资源清理
输入输出约定: 注册关闭回调，收到信号后按顺序执行清理
失败策略: 清理回调的异常会被记录但不会阻止其他回调执行
取消语义: 关闭流程本身不可取消
不适用场景: 简单脚本，不需要信号处理的场景
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import threading
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class GracefulShutdown:
    """跨平台的优雅关闭助手。

    在 Unix 上使用 loop.add_signal_handler；
    在 Windows 上回退到 threading.Event + signal.signal。
    """

    def __init__(self) -> None:
        self._cleanup_callbacks: list[Callable[[], Coroutine[Any, Any, None]]] = []
        self._shutdown_event: asyncio.Event | None = None
        self._thread_event: threading.Event = threading.Event()

    # ---- public API ----------------------------------------------------------

    def add_cleanup(self, callback: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """注册一个异步清理回调，关闭时按 LIFO（后注册先执行）顺序执行。

        LIFO 顺序更安全：后启动的组件通常依赖先启动的组件，应先关闭。
        """
        self._cleanup_callbacks.append(callback)

    def install_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        """注册 SIGINT / SIGTERM 信号处理器。"""
        self._shutdown_event = asyncio.Event()

        if sys.platform == "win32":
            # Windows 不支持 loop.add_signal_handler，回退到 signal.signal
            def _handler(signum: int, _frame: Any) -> None:
                logger.info("received signal %s (via signal.signal)", signum)
                self._thread_event.set()
                if self._shutdown_event is not None:
                    loop.call_soon_threadsafe(self._shutdown_event.set)

            signal.signal(signal.SIGINT, _handler)
            signal.signal(signal.SIGTERM, _handler)
        else:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(
                    sig,
                    self._on_signal,
                    sig,
                )

    async def wait(self) -> None:
        """阻塞直到收到关闭信号。"""
        if self._shutdown_event is None:
            raise RuntimeError("call install_signal_handlers() first")
        await self._shutdown_event.wait()

    async def run_cleanup(self, timeout: float = 30.0) -> None:
        """按 LIFO 顺序执行所有清理回调，单个失败不阻止后续执行。

        整体清理有超时保护，防止某个回调卡死导致进程无法退出。
        清理流程不可被外层取消中断——收到 CancelledError 后会继续完成清理，
        最后再重新抛出。
        """
        callbacks = list(reversed(self._cleanup_callbacks))
        logger.info("running %s cleanup callback(s) (LIFO order, timeout=%.1fs)...", len(callbacks), timeout)
        cancelled_during_cleanup = False
        try:
            async with asyncio.timeout(timeout):
                for i, cb in enumerate(callbacks):
                    try:
                        await asyncio.shield(cb())
                    except asyncio.CancelledError:
                        cancelled_during_cleanup = True
                        logger.warning("cleanup callback #%s received cancel, continuing cleanup", i)
                    except Exception:
                        logger.exception("cleanup callback #%s failed", i)
        except TimeoutError:
            logger.warning("cleanup timed out after %.1fs, skipping remaining callbacks", timeout)
        logger.info("cleanup phase finished")
        if cancelled_during_cleanup:
            raise asyncio.CancelledError("re-raised after cleanup completed")

    # ---- internal ------------------------------------------------------------

    def _on_signal(self, sig: signal.Signals) -> None:
        logger.info("received signal %s", sig.name)
        self._thread_event.set()
        if self._shutdown_event is not None:
            self._shutdown_event.set()


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

async def _demo() -> None:
    shutdown = GracefulShutdown()
    loop = asyncio.get_running_loop()
    shutdown.install_signal_handlers(loop)

    async def cleanup_db() -> None:
        logger.info("closing database connections...")
        await asyncio.sleep(0.2)
        logger.info("database connections closed")

    async def cleanup_cache() -> None:
        logger.info("flushing cache...")
        await asyncio.sleep(0.1)
        logger.info("cache flushed")

    shutdown.add_cleanup(cleanup_db)
    shutdown.add_cleanup(cleanup_cache)

    logger.info("application running, press Ctrl+C to stop")
    await shutdown.wait()
    await shutdown.run_cleanup()
    logger.info("shutdown complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    asyncio.run(_demo())
