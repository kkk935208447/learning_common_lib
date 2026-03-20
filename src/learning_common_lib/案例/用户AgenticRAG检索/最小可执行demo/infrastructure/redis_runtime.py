"""Redis-backed lock and lightweight runtime/session cache adapters."""

from __future__ import annotations

import json
import uuid
from typing import Any

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

try:
    from ..config import get_settings
    from ..ports.session_store_port import SessionStorePort
except ImportError:
    from 最小可执行demo.config import get_settings
    from 最小可执行demo.ports.session_store_port import SessionStorePort


class RedisDistributedLock:
    def __init__(self) -> None:
        self.client = Redis.from_url(get_settings().redis_lock_url, decode_responses=True)

    def try_lock(self, key: str, ttl_seconds: int) -> str | None:
        token = str(uuid.uuid4())
        acquired = self.client.set(key, token, nx=True, ex=ttl_seconds)
        return token if acquired else None

    def release(self, key: str, token: str) -> None:
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
        """
        self.client.eval(script, 1, key, token)


class RedisSessionStore(SessionStorePort):
    """Thin JSON store for session summaries, L2 staging, and runtime cache."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = AsyncRedis.from_url(self._settings.redis_cache_url, decode_responses=True)

    def _key(self, namespace: str, key: str) -> str:
        return f"{self._settings.cache_prefix}:{namespace}:{key}"

    async def load_namespace(self, namespace: str, key: str) -> dict[str, Any] | None:
        raw = await self._client.get(self._key(namespace, key))
        if raw is None:
            return None
        return json.loads(raw)

    async def save_namespace(
        self,
        namespace: str,
        key: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds or self._settings.runtime_cache_ttl_seconds
        await self._client.set(self._key(namespace, key), json.dumps(payload, ensure_ascii=False), ex=ttl)

    async def delete_namespace(self, namespace: str, key: str) -> None:
        await self._client.delete(self._key(namespace, key))

    async def aclose(self) -> None:
        await self._client.aclose()


class RedisRuntime:
    """Small runtime bundle kept for compatibility with the application layer."""

    def __init__(self) -> None:
        self.lock = RedisDistributedLock()
        self.session_store = RedisSessionStore()

    async def load_json(self, namespace: str, key: str) -> dict[str, Any] | None:
        return await self.session_store.load_namespace(namespace, key)

    async def save_json(
        self,
        namespace: str,
        key: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        await self.session_store.save_namespace(namespace, key, payload, ttl_seconds=ttl_seconds)

    async def delete_json(self, namespace: str, key: str) -> None:
        await self.session_store.delete_namespace(namespace, key)
