"""Redis-first 运行时配置。

为生产章节和模板提供统一的 Redis / thread_id / key prefix 约定，
保持配置集中且易读，不引入复杂配置框架。
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass


@dataclass(slots=True)
class RedisRuntimeSettings:
    """教程生产章节默认的 Redis 运行时配置。"""

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
