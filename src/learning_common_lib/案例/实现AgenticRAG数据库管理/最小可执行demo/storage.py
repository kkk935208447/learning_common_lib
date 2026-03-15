from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import uuid4

try:
    from .config import get_settings
except ImportError:
    from config import get_settings


class BaseObjectStorage(ABC):
    @abstractmethod
    async def put(self, storage_key: str, content: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get(self, storage_key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, storage_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def exists(self, storage_key: str) -> bool:
        raise NotImplementedError


class FileObjectStorage(BaseObjectStorage):
    def __init__(self, root_dir: Path | None = None) -> None:
        settings = get_settings()
        self.root_dir = root_dir or (settings.runtime_dir / "object_store")
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, storage_key: str) -> Path:
        path = self.root_dir / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def put(self, storage_key: str, content: bytes) -> None:
        path = self._resolve(storage_key)
        tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")

        def _write() -> None:
            tmp_path.write_bytes(content)
            tmp_path.replace(path)

        await asyncio.to_thread(_write)

    async def get(self, storage_key: str) -> bytes:
        path = self._resolve(storage_key)
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, storage_key: str) -> None:
        path = self._resolve(storage_key)
        if path.exists():
            await asyncio.to_thread(path.unlink)

    async def exists(self, storage_key: str) -> bool:
        return self._resolve(storage_key).exists()
