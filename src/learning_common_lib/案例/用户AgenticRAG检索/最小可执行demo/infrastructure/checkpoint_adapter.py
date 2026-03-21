"""Thin checkpoint adapter around the shared LangGraph checkpoint manager."""

from __future__ import annotations

from typing import Any

try:
    from .langgraph_checkpoint_support import (
        CheckpointManager as TemplateCheckpointManager,
        RedisRuntimeSettings,
    )
    from ..config import get_settings
    from ..ports.checkpoint_port import CheckpointPort
except ImportError:
    from 最小可执行demo.infrastructure.langgraph_checkpoint_support import (
        CheckpointManager as TemplateCheckpointManager,
        RedisRuntimeSettings,
    )
    from 最小可执行demo.config import get_settings
    from 最小可执行demo.ports.checkpoint_port import CheckpointPort


class LangGraphCheckpointAdapter(CheckpointPort):
    def __init__(self) -> None:
        settings = get_settings()
        runtime_settings = RedisRuntimeSettings(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            checkpoint_db=settings.redis_checkpoint_db,
            store_db=settings.redis_checkpoint_db,
            cache_db=settings.redis_cache_db,
            checkpoint_prefix=settings.checkpoint_prefix,
            checkpoint_write_prefix=settings.checkpoint_write_prefix,
            store_prefix=f"{settings.cache_prefix}_store",
            vector_prefix=f"{settings.cache_prefix}_vectors",
        )
        self._manager = TemplateCheckpointManager(settings=runtime_settings)
        self.backend = "memory"
        self.degraded = False
        self.last_error: str | None = None

    async def get_checkpointer(self) -> Any:
        checkpointer = await self._manager.get_checkpointer()
        self.backend = self._manager.backend
        self.degraded = self._manager.degraded
        self.last_error = self._manager.last_error
        return checkpointer

    async def aclose(self) -> None:
        await self._manager.aclose()
