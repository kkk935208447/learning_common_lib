"""File-based object storage mock used to simulate OSS-style source files."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import uuid4

try:
    from .config import get_settings
except ImportError:
    from config import get_settings


# 对象存储接口故意保持很薄，方便后续替换成真实 OSS SDK。
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
        # 文件系统 mock 让不同进程之间也能共享同一份“对象存储”状态。
        self.root_dir = root_dir or (settings.runtime_dir / "object_store")
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, storage_key: str) -> Path:
        # storage_key 和磁盘路径 1:1 对应，便于肉眼从目录结构看出文档版本关系。
        return self.root_dir / storage_key

    def _resolve_for_write(self, storage_key: str) -> Path:
        # 写入前保证目录结构存在，调用方不需要关心路径准备细节。
        path = self._path(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def put(self, storage_key: str, content: bytes) -> None:
        path = self._resolve_for_write(storage_key)
        tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")

        def _write() -> None:
            # 对象写入采用原子替换，避免上传过程中留下半写入文件。
            tmp_path.write_bytes(content)
            tmp_path.replace(path)

        await asyncio.to_thread(_write)

    async def get(self, storage_key: str) -> bytes:
        path = self._path(storage_key)
        # 读取端保持最简单：对象不存在时直接让底层抛错，再由上层决定如何补偿。
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, storage_key: str) -> None:
        path = self._path(storage_key)
        if path.exists():
            # 删除采用“存在才删”的宽松语义，避免清理任务因为对象已不存在而失败。
            await asyncio.to_thread(path.unlink)

    async def exists(self, storage_key: str) -> bool:
        # exists 主要给上传后回读校验或测试场景使用。
        return self._path(storage_key).exists()
