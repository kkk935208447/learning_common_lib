"""Local LangGraph checkpoint helpers kept inside the demo project tree."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.redis.aio import AsyncKeyRegistry

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RedisRuntimeSettings:
    host: str = os.getenv("LANGGRAPH_REDIS_HOST", "localhost")
    port: int = int(os.getenv("LANGGRAPH_REDIS_PORT", "6379"))
    password: str = os.getenv("LANGGRAPH_REDIS_PASSWORD", "123456")
    checkpoint_db: int = int(os.getenv("LANGGRAPH_REDIS_CHECKPOINT_DB", "0"))
    store_db: int = int(os.getenv("LANGGRAPH_REDIS_STORE_DB", "0"))
    cache_db: int = int(os.getenv("LANGGRAPH_REDIS_CACHE_DB", "2"))
    checkpoint_prefix: str = os.getenv(
        "LANGGRAPH_CHECKPOINT_PREFIX",
        os.getenv("LANGGRAPH_CHECKPOINT_STORE_PREFIX", "lg_tutorial_cp"),
    )
    checkpoint_write_prefix: str = os.getenv(
        "LANGGRAPH_CHECKPOINT_WRITE_PREFIX",
        "lg_tutorial_cp_writes",
    )
    store_prefix: str = os.getenv("LANGGRAPH_STORE_PREFIX", "lg_tutorial_store")
    vector_prefix: str = os.getenv("LANGGRAPH_VECTOR_PREFIX", "lg_tutorial_store_vectors")

    @property
    def auth_part(self) -> str:
        return f":{self.password}@" if self.password else ""

    def redis_url(self, db: int) -> str:
        return f"redis://{self.auth_part}{self.host}:{self.port}/{db}"

    @property
    def checkpoint_url(self) -> str:
        return self.redis_url(self.checkpoint_db)

    @property
    def store_url(self) -> str:
        return self.redis_url(self.store_db)

    @property
    def cache_url(self) -> str:
        return self.redis_url(self.cache_db)

    @property
    def celery_broker_url(self) -> str:
        return self.checkpoint_url

    @property
    def celery_backend_url(self) -> str:
        return self.store_url

    @property
    def strict_redis(self) -> bool:
        return os.getenv("LANGGRAPH_STRICT_REDIS", "1") != "0"

    def global_thread_id(self, tenant_id: str, task_id: str | int) -> str:
        return f"tenant:{tenant_id}:task:{task_id}"

    def subtask_thread_id(
        self,
        tenant_id: str,
        task_id: str | int,
        plan_version: int,
        subtask_code: str,
        execution_id: str,
    ) -> str:
        return (
            f"tenant:{tenant_id}:task:{task_id}:plan:{plan_version}:"
            f"subtask:{subtask_code}:exec:{execution_id}"
        )

    def demo_suffix(self, label: str) -> str:
        return f"{label}-{uuid.uuid4().hex[:8]}"

    def demo_thread_id(self, label: str, *, tenant_id: str = "demo") -> str:
        return self.global_thread_id(tenant_id, self.demo_suffix(label))

    def demo_user_id(self, label: str = "user") -> str:
        return self.demo_suffix(label)

    def chat_namespace(self, thread_id: str) -> tuple[str, str, str]:
        return ("threads", thread_id, "chat")

    def preference_namespace(self, user_id: str) -> tuple[str, str, str]:
        return ("users", user_id, "preferences")

    def profile_namespace(self, user_id: str) -> tuple[str, str, str]:
        return ("users", user_id, "profile")


DEFAULT_RUNTIME_SETTINGS = RedisRuntimeSettings()


def diagnose_redis_error(exc: Exception) -> str:
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
    def __init__(
        self,
        redis_url: str | None = None,
        *,
        settings: RedisRuntimeSettings | None = None,
        prefer_redis: bool | None = None,
    ) -> None:
        self._settings = settings or DEFAULT_RUNTIME_SETTINGS
        self._prefer_redis = True if prefer_redis is None else prefer_redis
        self._redis_url = redis_url or self._settings.checkpoint_url if self._prefer_redis else None
        self.backend = "memory"
        self.degraded = False
        self.last_error: str | None = None
        self._checkpointer_cm: Any | None = None
        self._checkpointer: Any | None = None

    async def _reuse_existing_indexes(self, saver_cls: type[Any]) -> Any:
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
        if self._checkpointer_cm is not None:
            await self._checkpointer_cm.__aexit__(None, None, None)
            self._checkpointer_cm = None
        self._checkpointer = None


async def get_checkpointer(
    redis_url: str | None = None,
    *,
    settings: RedisRuntimeSettings | None = None,
    prefer_redis: bool | None = None,
) -> Any:
    manager = CheckpointManager(
        redis_url=redis_url,
        settings=settings,
        prefer_redis=prefer_redis,
    )
    saver = await manager.get_checkpointer()
    return _attach_helper_state(saver, manager)
