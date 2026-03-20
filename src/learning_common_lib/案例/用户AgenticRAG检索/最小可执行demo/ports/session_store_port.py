"""Redis-backed session/runtime store port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SessionStorePort(ABC):
    @abstractmethod
    async def load_namespace(self, namespace: str, key: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def save_namespace(
        self,
        namespace: str,
        key: str,
        payload: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_namespace(self, namespace: str, key: str) -> None:
        raise NotImplementedError
