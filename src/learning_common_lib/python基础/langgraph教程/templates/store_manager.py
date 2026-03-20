"""Store 管理器：Redis-first，失败时降级为内存 Store。"""
from __future__ import annotations

from contextlib import suppress
import logging
from typing import Any

from langgraph.store.memory import InMemoryStore

try:
    from .checkpoint_manager import diagnose_redis_error
    from .runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings
except ImportError:  # pragma: no cover - 允许直接运行模板文件
    from checkpoint_manager import diagnose_redis_error
    from runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings

logger = logging.getLogger(__name__)


class ResilientStore:
    """对底层 Store 做一层轻量包装，暴露 backend 信息便于日志与调试。"""

    def __init__(
        self,
        store: Any,
        *,
        backend: str,
        degraded: bool,
        last_error: str | None = None,
        owner: StoreManager | None = None,
    ) -> None:
        self._store = store
        self.backend = backend
        self.degraded = degraded
        self.last_error = last_error
        self._owner = owner
        self.underlying_type_name = type(store).__name__

    async def aclose(self) -> None:
        if self._owner is not None:
            await self._owner.aclose()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def __repr__(self) -> str:
        return (
            "ResilientStore("
            f"type={self.underlying_type_name}, backend={self.backend}, degraded={self.degraded}"
            ")"
        )


class StoreManager:
    """Redis-first Store 管理器。

    默认优先连接 RedisStore；初始化失败时回退到 InMemoryStore，
    同时明确打印降级原因，避免“假成功”。
    """

    def __init__(
        self,
        settings: RedisRuntimeSettings | None = None,
        *,
        prefer_redis: bool | None = None,
    ) -> None:
        self._settings = settings or DEFAULT_RUNTIME_SETTINGS
        self._prefer_redis = True if prefer_redis is None else prefer_redis
        self.backend = "memory"
        self.degraded = False
        self.last_error: str | None = None
        self._store_cm: Any | None = None
        self._store: ResilientStore | None = None

    async def get_store(self) -> ResilientStore:
        if self._store is not None:
            return self._store

        if self._prefer_redis:
            try:
                from langgraph.store.redis import RedisStore  # type: ignore[import-untyped]

                self._store_cm = RedisStore.from_conn_string(
                    self._settings.store_url,
                    store_prefix=self._settings.store_prefix,
                    vector_prefix=self._settings.vector_prefix,
                )
                try:
                    store = self._store_cm.__enter__()
                    store.setup()
                except Exception:
                    with suppress(Exception):
                        self._store_cm.__exit__(None, None, None)
                    self._store_cm = None
                    raise
                logger.info("使用 Redis store: %s", self._settings.store_url)
                self.backend = "redis"
                self.degraded = False
                self.last_error = None
                self._store = ResilientStore(
                    store,
                    backend="redis",
                    degraded=False,
                    owner=self,
                )
                return self._store
            except Exception as exc:
                diagnosis = diagnose_redis_error(exc)
                self.backend = "memory"
                self.degraded = True
                self.last_error = f"{type(exc).__name__}: {exc} | {diagnosis}"
                logger.warning(
                    "Redis store 不可用(当前 store_url=%s)，降级为 InMemoryStore: %s",
                    self._settings.store_url,
                    self.last_error,
                )

        store = InMemoryStore()
        self._store = ResilientStore(
            store,
            backend="memory",
            degraded=self._prefer_redis,
            last_error=self.last_error,
            owner=self,
        )
        return self._store

    async def aclose(self) -> None:
        if self._store_cm is not None:
            self._store_cm.__exit__(None, None, None)
            self._store_cm = None
        self._store = None


async def get_store(
    settings: RedisRuntimeSettings | None = None,
    *,
    prefer_redis: bool | None = None,
) -> ResilientStore:
    mgr = StoreManager(settings=settings, prefer_redis=prefer_redis)
    return await mgr.get_store()


async def _demo() -> None:
    mgr = StoreManager(prefer_redis=False)
    store = await mgr.get_store()
    print(
        f"store backend: {store.backend}, degraded={store.degraded} "
        f"last_error={store.last_error}"
    )
    mgr_redis = StoreManager()
    store_redis = await mgr_redis.get_store()
    print(
        f"redis-first store backend: {store_redis.backend}, degraded={store_redis.degraded} "
        f"last_error={store_redis.last_error}"
    )
    await mgr_redis.aclose()
    await mgr.aclose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_demo())
