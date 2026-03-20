"""Object storage read port."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ObjectStorageReadPort(ABC):
    @abstractmethod
    async def get(self, storage_key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def exists(self, storage_key: str) -> bool:
        raise NotImplementedError
