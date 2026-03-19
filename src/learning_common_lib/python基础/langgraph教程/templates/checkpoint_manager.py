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

    说明：
        `langgraph-checkpoint-redis` 依赖带 RediSearch 能力的 Redis/Redis Stack。
        如果只是普通 Redis 实例，初始化时可能因 `FT._LIST` 等命令缺失而自动降级。
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._checkpointer_cm: Any | None = None
        self._checkpointer: Any | None = None

    async def get_checkpointer(self) -> Any:
        """获取 checkpointer 实例，Redis 不可用时自动降级为内存。"""
        if self._checkpointer is not None:
            return self._checkpointer

        if self._redis_url:
            try:
                from langgraph.checkpoint.redis.aio import AsyncRedisSaver  # type: ignore[import-untyped]

                self._checkpointer_cm = AsyncRedisSaver.from_conn_string(self._redis_url)
                saver = await self._checkpointer_cm.__aenter__()
                await saver.asetup()
                logger.info("使用 Redis checkpointer: %s", self._redis_url)
                self._checkpointer = ResilientCheckpointer(saver)
                return self._checkpointer
            except Exception:
                logger.warning("Redis 不可用，降级为内存 checkpointer")
        self._checkpointer = MemorySaver()
        return self._checkpointer

    async def aclose(self) -> None:
        """关闭内部维护的异步 checkpointer 资源。"""
        if self._checkpointer_cm is not None:
            await self._checkpointer_cm.__aexit__(None, None, None)
            self._checkpointer_cm = None
        self._checkpointer = None


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
    await mgr_redis.aclose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_demo())
