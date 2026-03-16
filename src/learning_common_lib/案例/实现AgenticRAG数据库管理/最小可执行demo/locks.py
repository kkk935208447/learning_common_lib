"""Distributed lock adapter backed by Redis for leader and task exclusion locks."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from redis import Redis

try:
    from .config import get_settings
except ImportError:
    from config import get_settings


class BaseDistributedLock(ABC):
    @abstractmethod
    def try_lock(self, key: str, ttl_seconds: int) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def release(self, key: str, token: str) -> None:
        raise NotImplementedError


class RedisDistributedLock(BaseDistributedLock):
    def __init__(self) -> None:
        settings = get_settings()
        self.client = Redis.from_url(settings.redis_lock_url, decode_responses=True)

    def try_lock(self, key: str, ttl_seconds: int) -> str | None:
        token = str(uuid.uuid4())
        # Redis 的 `SET NX EX` 足够演示最小分布式锁语义。
        acquired = self.client.set(key, token, nx=True, ex=ttl_seconds)
        return token if acquired else None

    def release(self, key: str, token: str) -> None:
        # compare-and-delete，防止误删掉别人后来抢到的同名锁。
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
        """
        self.client.eval(script, 1, key, token)
