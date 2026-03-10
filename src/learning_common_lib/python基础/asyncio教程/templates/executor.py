"""
解决什么问题: 提供有并发上限、单任务超时、结构化结果的异步执行器
输入输出约定: 传入协程工厂列表，返回 list[TaskResult]
失败策略: 单任务失败不影响其他任务，失败信息记录在 TaskResult 中
取消语义: 外部取消会传播到所有正在执行的任务
不适用场景: 需要任务间依赖或编排的场景，应使用专门的工作流引擎
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

try:
    from .result_types import TaskResult
except ImportError:
    from result_types import TaskResult

logger = logging.getLogger(__name__)


class AsyncExecutor:
    """有并发上限、单任务超时、结构化结果的异步执行器。"""

    def __init__(self, concurrency: int = 10, timeout: float = 10.0) -> None:
        self._sem = asyncio.Semaphore(concurrency)
        self._timeout = timeout

    async def run_one(
        self,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        name: str,
    ) -> TaskResult:
        async with self._sem:
            try:
                async with asyncio.timeout(self._timeout):
                    result = await coro_factory()
                    logger.info("task success: %s", name)
                    return TaskResult.success(name, result)
            except TimeoutError:
                logger.warning("task timeout: %s", name)
                return TaskResult.from_timeout(name)
            except asyncio.CancelledError:
                logger.warning("task cancelled: %s", name)
                raise
            except Exception as exc:
                logger.exception("task failed: %s", name)
                return TaskResult.from_error(name, exc)

    async def run_many(
        self,
        jobs: Sequence[tuple[str, Callable[[], Awaitable[Any]]]],
    ) -> list[TaskResult]:
        """批量执行任务，通过 Semaphore 控制同时执行的并发数。

        注意：TaskGroup 会一次性为所有 job 创建 Task 对象（轻量），
        但 Semaphore 保证同时 *执行* 的不超过 concurrency 个。
        对于超大批量（10 万+）场景，建议改用 Queue + worker pool 模式
        以避免一次性创建大量 Task 对象占用内存。

        Args:
            jobs: [(name, coro_factory), ...] 列表

        Returns:
            与 jobs 同序的 TaskResult 列表
        """
        results: list[TaskResult] = [TaskResult.from_cancelled("") for _ in jobs]

        async def _slot(idx: int, name: str, factory: Callable[[], Awaitable[Any]]) -> None:
            results[idx] = await self.run_one(factory, name=name)

        async with asyncio.TaskGroup() as tg:
            for idx, (name, factory) in enumerate(jobs):
                tg.create_task(_slot(idx, name, factory), name=name)

        return results


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

async def _fake_api_call(item_id: int) -> dict[str, Any]:
    await asyncio.sleep(random.uniform(0.2, 1.5))
    if random.random() < 0.2:
        raise RuntimeError(f"fake api error: {item_id}")
    return {"item_id": item_id, "value": item_id * 100}


async def _demo() -> None:
    executor = AsyncExecutor(concurrency=5, timeout=3)

    jobs: list[tuple[str, Callable[[], Awaitable[Any]]]] = [
        (f"job-{i}", lambda item_id=i: _fake_api_call(item_id))
        for i in range(20)
    ]

    results = await executor.run_many(jobs)
    success = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    logger.info("summary: success=%s failed=%s", len(success), len(failed))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    asyncio.run(_demo())
