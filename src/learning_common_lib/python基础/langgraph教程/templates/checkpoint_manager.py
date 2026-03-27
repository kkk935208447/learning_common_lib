"""
Checkpoint 管理器：Redis / 内存自动切换，为 LangGraph 图提供持久化能力。

目标:
    Checkpoint 管理器：Redis / 内存自动切换，为 LangGraph 图提供持久化能力。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    见本文件导入、节点函数和构图代码

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: templates/checkpoint_manager.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python templates/checkpoint_manager.py

预期现象:
    运行后可观察本文件对应的状态推进、输出或集成行为

生产提醒:
    迁移到业务代码前，请结合 README / best_practices / pitfalls 一起阅读
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.redis.aio import AsyncKeyRegistry

try:
    from .runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings
except ImportError:  # pragma: no cover - 允许直接运行模板文件
    from runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings

logger = logging.getLogger(__name__)


def diagnose_redis_error(exc: Exception) -> str:
    """把常见 Redis 初始化错误归类为可读诊断信息。"""
    message = str(exc)
    lowered = message.lower()
    hints: list[str] = []

    if "cannot create index on db != 0" in lowered:
        hints.append("RediSearch 只允许在 db=0 上创建索引，请设置 LANGGRAPH_REDIS_STORE_DB=0")
    if "ft._list" in lowered or ("unknown command" in lowered and "ft." in lowered):
        hints.append("当前 Redis 缺少 RediSearch / Redis Stack 能力")
    if "wrongpass" in lowered or "invalid password" in lowered or "authentication" in lowered or "noauth" in lowered:
        hints.append("Redis 认证失败，请检查密码或 ACL 配置")
    if (
        "connection refused" in lowered
        or "operation not permitted" in lowered
        or "timed out" in lowered
        or "name or service not known" in lowered
        or "nodename nor servname provided" in lowered
    ):
        hints.append("Redis 不可达，请检查服务、主机端口或本地网络访问权限")

    if not hints:
        hints.append("请检查 Redis 地址、认证信息以及 RediSearch 能力")
    return "；".join(dict.fromkeys(hints))


def _attach_helper_state(saver: Any, manager: "CheckpointManager") -> Any:
    saver.backend = manager.backend
    saver.degraded = manager.degraded
    saver.last_error = manager.last_error
    saver.underlying_type_name = type(saver).__name__
    saver.aclose = manager.aclose
    saver.close_manager = manager.aclose
    return saver

class CheckpointManager:
    """Checkpoint 管理器，支持 Redis / 内存自动切换。

    用法::

        mgr = CheckpointManager(redis_url="redis://:123456@localhost:6379/0")
        checkpointer = await mgr.get_checkpointer()

    说明：
        `langgraph-checkpoint-redis` 依赖带 RediSearch 能力的 Redis/Redis Stack。
        如果只是普通 Redis 实例，初始化时可能因 `FT._LIST` 等命令缺失而自动降级。
    """

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        settings: RedisRuntimeSettings | None = None,
        prefer_redis: bool | None = None,
    ) -> None:
        self._settings = settings or DEFAULT_RUNTIME_SETTINGS
        self._prefer_redis = True if prefer_redis is None else prefer_redis
        self._redis_url = (
            redis_url or self._settings.checkpoint_url
            if self._prefer_redis
            else None
        )
        self.backend = "memory"
        self.degraded = False
        self.last_error: str | None = None
        self._checkpointer_cm: Any | None = None
        self._checkpointer: Any | None = None

    async def _reuse_existing_indexes(self, saver_cls: type[Any]) -> Any:
        """复用已存在的 RediSearch 索引，避免重复运行时误判为不可用。"""
        saver = saver_cls(
            redis_url=self._redis_url,
            checkpoint_prefix=self._settings.checkpoint_prefix,
            checkpoint_write_prefix=self._settings.checkpoint_write_prefix,
        )
        self._checkpointer_cm = saver
        saver.create_indexes()
        await saver._detect_cluster_mode()
        saver._key_registry = AsyncKeyRegistry(saver._redis)
        await saver.aset_client_info()
        logger.info(
            "Redis checkpoint 索引已存在，复用现有索引: prefix=%s write_prefix=%s",
            self._settings.checkpoint_prefix,
            self._settings.checkpoint_write_prefix,
        )
        return saver

    async def get_checkpointer(self) -> Any:
        """获取 checkpointer 实例，Redis 不可用时自动降级为内存。"""
        if self._checkpointer is not None:
            return self._checkpointer

        if self._redis_url:
            try:
                from langgraph.checkpoint.redis.aio import AsyncRedisSaver  # type: ignore[import-untyped]

                self._checkpointer_cm = AsyncRedisSaver.from_conn_string(
                    self._redis_url,
                    checkpoint_prefix=self._settings.checkpoint_prefix,
                    checkpoint_write_prefix=self._settings.checkpoint_write_prefix,
                )
                try:
                    saver = await self._checkpointer_cm.__aenter__()
                except Exception as exc:
                    if "index already exists" not in str(exc).lower():
                        raise
                    saver = await self._reuse_existing_indexes(AsyncRedisSaver)
                logger.info("使用 Redis checkpointer: %s", self._redis_url)
                self.backend = "redis"
                self.degraded = False
                self.last_error = None
                self._checkpointer = saver
                return self._checkpointer
            except Exception as exc:
                diagnosis = diagnose_redis_error(exc)
                self.backend = "memory"
                self.degraded = True
                self.last_error = f"{type(exc).__name__}: {exc} | {diagnosis}"
                logger.warning(
                    "Redis checkpoint 不可用，降级为内存 checkpointer: %s",
                    self.last_error,
                )
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

async def get_checkpointer(
    redis_url: str | None = None,
    *,
    settings: RedisRuntimeSettings | None = None,
    prefer_redis: bool | None = None,
) -> Any:
    """快捷方式：获取 checkpointer。"""
    mgr = CheckpointManager(
        redis_url=redis_url,
        settings=settings,
        prefer_redis=prefer_redis,
    )
    saver = await mgr.get_checkpointer()
    return _attach_helper_state(saver, mgr)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

async def _demo() -> None:
    """演示 CheckpointManager 的使用。"""
    import asyncio

    # 1. 内存模式
    mgr = CheckpointManager(prefer_redis=False)
    cp = await mgr.get_checkpointer()
    print(
        f"内存 checkpointer: {type(cp).__name__} | "
        f"backend={mgr.backend} degraded={mgr.degraded}"
    )

    # 2. Redis 模式（可能降级）
    mgr_redis = CheckpointManager()
    cp_redis = await mgr_redis.get_checkpointer()
    print(
        f"Redis checkpointer: {type(cp_redis).__name__} | "
        f"backend={mgr_redis.backend} degraded={mgr_redis.degraded} "
        f"last_error={mgr_redis.last_error}"
    )
    await mgr_redis.aclose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_demo())
