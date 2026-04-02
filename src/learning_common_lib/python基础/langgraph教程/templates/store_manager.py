"""
Store 管理器：Redis-first，失败时降级为内存 Store。

目标:
    Store 管理器：Redis-first，失败时降级为内存 Store。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    见本文件导入、节点函数和构图代码

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: templates/store_manager.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python templates/store_manager.py

预期现象:
    运行后可观察本文件对应的状态推进、输出或集成行为

生产提醒:
    迁移到业务代码前，请结合 README / best_practices / pitfalls 一起阅读
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langgraph.store.memory import InMemoryStore

try:
    from .checkpoint_manager import diagnose_redis_error
    from .runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings
except ImportError:  # pragma: no cover - 允许直接运行模板文件
    from checkpoint_manager import diagnose_redis_error
    from runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings

if TYPE_CHECKING:
    from langgraph.store.redis.aio import AsyncRedisStore

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

    默认优先连接 AsyncRedisStore；初始化失败时回退到 InMemoryStore，
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

    def _build_async_store(self, store_cls: type["AsyncRedisStore"]) -> "AsyncRedisStore":
        return store_cls(
            redis_url=self._settings.store_url,
            store_prefix=self._settings.store_prefix,
            vector_prefix=self._settings.vector_prefix,
        )

    async def _close_failed_store(self, store: "AsyncRedisStore", exc: BaseException | None = None) -> None:
        try:
            await store.__aexit__(
                type(exc) if exc is not None else None,
                exc,
                exc.__traceback__ if exc is not None else None,
            )
        except Exception:
            logger.debug("关闭失败的 Redis store 时再次出错", exc_info=True)

    async def _create_index_allow_existing(self, index: Any) -> None:
        try:
            await index.create(overwrite=False)
        except Exception as exc:
            if "index already exists" not in str(exc).lower():
                raise

    async def _setup_store_allow_existing_indexes(self, store: "AsyncRedisStore") -> None:
        if getattr(store, "cluster_mode", None) is None:
            await store._detect_cluster_mode()
        await self._create_index_allow_existing(store.store_index)
        if getattr(store, "index_config", None):
            await self._create_index_allow_existing(store.vector_index)

    async def get_store(self) -> ResilientStore:
        if self._store is not None:
            return self._store

        if self._prefer_redis:
            try:
                from langgraph.store.redis.aio import AsyncRedisStore  # type: ignore[import-untyped]

                store = self._build_async_store(AsyncRedisStore)
                self._store_cm = store
                try:
                    await store.__aenter__()
                    try:
                        await store.setup()
                    except Exception as exc:
                        if "index already exists" not in str(exc).lower():
                            raise
                        await self._setup_store_allow_existing_indexes(store)
                    await store.aset_client_info()
                except Exception as exc:
                    await self._close_failed_store(store, exc)
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
            await self._store_cm.__aexit__(None, None, None)
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
    mgr = StoreManager(prefer_redis=False)    # 内存模式
    store = await mgr.get_store()
    print(
        f"store backend: {store.backend}, degraded={store.degraded} "
        f"last_error={store.last_error}"
    )
    await mgr.aclose()                        # 关闭内存模式

    mgr_redis = StoreManager()                # Redis 模式
    store_redis = await mgr_redis.get_store()
    print(
        f"redis-first store backend: {store_redis.backend}, degraded={store_redis.degraded} "
        f"last_error={store_redis.last_error}"
    )
    await mgr_redis.aclose()                  # 关闭 Redis 模式


if __name__ == "__main__":
    import asyncio

    asyncio.run(_demo())
