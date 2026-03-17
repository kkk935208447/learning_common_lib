"""File-based search store mock used to simulate ES-style text projections."""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import uuid4

try:
    from .config import get_settings
except ImportError:
    from config import get_settings


# 搜索库 mock 与向量库 mock 保持对称接口，便于 index/cleanup 统一处理。
class BaseSearchStore(ABC):
    @abstractmethod
    async def upsert_chunks(self, version_id: int, docs: list[dict]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_by_version(self, version_id: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def count_by_version(self, version_id: int) -> int:
        raise NotImplementedError


class FileSearchStore(BaseSearchStore):
    def __init__(self, root_dir: Path | None = None) -> None:
        settings = get_settings()
        # 文本投影落文件后，排查时可以直接打开 JSON 看内容和元数据。
        self.root_dir = root_dir or (settings.runtime_dir / "search_store")
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, chunk_uid: str) -> Path:
        return self.root_dir / f"{chunk_uid}.json"

    async def upsert_chunks(self, version_id: int, docs: list[dict]) -> None:
        def _write() -> None:
            for doc in docs:
                path = self._path(doc["chunk_uid"])
                tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
                # 保持和对象存储、向量存储一致的原子写策略，减少 mock 数据损坏窗口。
                tmp_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp_path.replace(path)

        await asyncio.to_thread(_write)

    async def delete_by_version(self, version_id: int) -> None:
        def _delete() -> None:
            # 这里和向量库一样按 version 粒度清理，保证两个投影侧行为一致。
            for path in self.root_dir.glob("*.json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("version_id") == version_id:
                    path.unlink(missing_ok=True)

        await asyncio.to_thread(_delete)

    async def count_by_version(self, version_id: int) -> int:
        def _count() -> int:
            count = 0
            # 文件型 mock 直接扫目录即可，代价是性能一般，但逻辑非常直观。
            for path in self.root_dir.glob("*.json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("version_id") == version_id:
                    count += 1
            return count

        return await asyncio.to_thread(_count)
