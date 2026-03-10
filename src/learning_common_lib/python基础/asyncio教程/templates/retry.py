"""
解决什么问题: 为异步调用提供指数退避重试，带 jitter
输入输出约定: 传入异步工厂函数，返回其结果或抛出最后一次异常
失败策略: 达到最大重试次数后抛出原始异常
取消语义: CancelledError 不会被重试，直接传播
不适用场景: 参数错误、权限错误、业务逻辑错误等不可恢复异常
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


async def retry_with_backoff(
    func: Callable[[], Awaitable[Any]],
    *,
    retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 5.0,
    retry_exceptions: tuple[type[Exception], ...] = (
        OSError,
        TimeoutError,
        ConnectionError,
    ),
) -> Any:
    """带指数退避和 jitter 的异步重试。

    默认只重试 *可恢复* 的异常（网络 / IO / 超时类）。
    业务逻辑错误、参数错误、权限错误等不应被重试——如果你把
    retry_exceptions 设为 ``(Exception,)``，一个 ValueError 也会被
    重试三次，这几乎不可能自愈，只会白白浪费时间。

    CancelledError 永远不会被重试，收到取消信号后立即传播。
    """
    last_exc: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            return await func()
        except asyncio.CancelledError:
            # 取消信号不可重试，直接传播
            raise
        except retry_exceptions as exc:
            last_exc = exc
            if attempt == retries:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            jitter = random.uniform(0, delay * 0.2)
            sleep_time = delay + jitter
            logger.warning(
                "retryable error, attempt=%s/%s sleep=%.2fs error=%s",
                attempt,
                retries,
                sleep_time,
                exc,
            )
            await asyncio.sleep(sleep_time)

    # 理论上不会到这里，但 mypy 需要
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

async def _flaky_operation() -> str:
    """模拟一个偶尔失败的网络调用。"""
    if random.random() < 0.6:
        raise ConnectionError("connection refused")
    return "success!"


async def _demo() -> None:
    try:
        result = await retry_with_backoff(_flaky_operation, retries=5)
        logger.info("got result: %s", result)
    except ConnectionError as exc:
        logger.error("all retries exhausted: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    asyncio.run(_demo())
