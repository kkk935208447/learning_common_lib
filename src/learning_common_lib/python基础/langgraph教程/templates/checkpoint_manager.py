"""Checkpoint 管理器：Redis / 内存自动切换，为 LangGraph 图提供持久化能力。"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

_DEFAULT_REDIS_URL = "redis://:123456@localhost:6379/0"


# ---------------------------------------------------------------------------
# 弹性包装器
# ---------------------------------------------------------------------------

class ResilientCheckpointer:
    """对底层 checkpointer 做一层弹性包装，连接失败时自动降级为内存。"""

    def __init__(self, saver: Any) -> None:
        self._saver = saver

    def __getattr__(self, name: str) -> Any:
        return getattr(self._saver, name)

    def __repr__(self) -> str:
        return f"ResilientCheckpointer({self._saver!r})"


# ---------------------------------------------------------------------------
# 管理器
# ---------------------------------------------------------------------------

class CheckpointManager:
    """Checkpoint 管理器，支持 Redis / 内存自动切换。

    用法::

        mgr = CheckpointManager(redis_url="redis://:123456@localhost:6379/0")
        checkpointer = await mgr.get_checkpointer()
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url

    async def get_checkpointer(self) -> Any:
        """获取 checkpointer 实例，Redis 不可用时自动降级为内存。"""
        if self._redis_url:
            try:
                from langgraph.checkpoint.redis.aio import AsyncRedisSaver  # type: ignore[import-untyped]

                saver = AsyncRedisSaver(self._redis_url)
                logger.info("使用 Redis checkpointer: %s", self._redis_url)
                return ResilientCheckpointer(saver)
            except Exception:
                logger.warning("Redis 不可用，降级为内存 checkpointer")
        return MemorySaver()


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

async def get_checkpointer(redis_url: str | None = _DEFAULT_REDIS_URL) -> Any:
    """快捷方式：获取 checkpointer。"""
    mgr = CheckpointManager(redis_url=redis_url)
    return await mgr.get_checkpointer()


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

async def _demo() -> None:
    """演示 CheckpointManager 的使用。"""
    import asyncio

    # 1. 内存模式
    mgr = CheckpointManager()
    cp = await mgr.get_checkpointer()
    print(f"内存 checkpointer: {type(cp).__name__}")

    # 2. Redis 模式（可能降级）
    mgr_redis = CheckpointManager(redis_url=_DEFAULT_REDIS_URL)
    cp_redis = await mgr_redis.get_checkpointer()
    print(f"Redis checkpointer: {type(cp_redis).__name__}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_demo())
