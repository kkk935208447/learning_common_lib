"""File-based vector store mock used to simulate Milvus-style projections."""

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


# 向量库接口只暴露 demo 当前需要的最小读写能力。
class BaseVectorStore(ABC):
    @abstractmethod
    async def upsert_chunks(self, version_id: int, records: list[dict]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_by_version(self, version_id: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def count_by_version(self, version_id: int) -> int:
        raise NotImplementedError

    @abstractmethod
    async def remove_one_for_version(self, version_id: int) -> bool:
        raise NotImplementedError


class FileVectorStore(BaseVectorStore):
    def __init__(self, root_dir: Path | None = None) -> None:
        settings = get_settings()
        # 每个 chunk 一个 JSON 文件，能直观看到投影结果，也方便手工篡改做 Janitor 演示。
        self.root_dir = root_dir or (settings.runtime_dir / "vector_store")
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, chunk_uid: str) -> Path:
        # chunk_uid 稳定后，同一 chunk 的多次 upsert 会直接覆盖同一文件。
        return self.root_dir / f"{chunk_uid}.json"

    async def upsert_chunks(self, version_id: int, records: list[dict]) -> None:
        def _write() -> None:
            # 这里不使用 version_id 目录分桶，是为了让 chunk_uid 成为唯一主键语义更直观。
            for record in records:
                path = self._path(record["chunk_uid"])
                tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
                # 先写临时文件再 replace，避免读取方看到半截 JSON。
                tmp_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp_path.replace(path)

        await asyncio.to_thread(_write)

    async def delete_by_version(self, version_id: int) -> None:
        def _delete() -> None:
            # 删除策略按 version_id 扫描，强调“索引投影可由 version 粒度整体回收”。
            for path in self.root_dir.glob("*.json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("version_id") == version_id:
                    path.unlink(missing_ok=True)

        await asyncio.to_thread(_delete)

    async def count_by_version(self, version_id: int) -> int:
        def _count() -> int:
            count = 0
            # 和 search_store 一样，直接扫描目录换取实现简单性。
            for path in self.root_dir.glob("*.json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("version_id") == version_id:
                    count += 1
            return count

        return await asyncio.to_thread(_count)

    async def remove_one_for_version(self, version_id: int) -> bool:
        def _remove() -> bool:
            # 这个辅助方法只给 demo_flow 做故障注入，正常主流程不会调用。
            for path in self.root_dir.glob("*.json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("version_id") == version_id:
                    path.unlink(missing_ok=True)
                    return True
            return False

        return await asyncio.to_thread(_remove)
