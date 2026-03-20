"""Object storage reader that reuses the upstream demo's file storage layout."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from ....实现AgenticRAG数据库管理.最小可执行demo.storage import FileObjectStorage
    from ..ports.object_storage_port import ObjectStorageReadPort
except ImportError:
    cases_root = Path(__file__).resolve().parent.parent.parent.parent
    if str(cases_root) not in sys.path:
        sys.path.insert(0, str(cases_root))
    from 实现AgenticRAG数据库管理.最小可执行demo.storage import FileObjectStorage
    from 最小可执行demo.ports.object_storage_port import ObjectStorageReadPort


class ObjectStorageReader(ObjectStorageReadPort):
    def __init__(self) -> None:
        self._storage = FileObjectStorage()

    async def get(self, storage_key: str) -> bytes:
        return await self._storage.get(storage_key)

    async def exists(self, storage_key: str) -> bool:
        return await self._storage.exists(storage_key)


FileObjectStorageReadAdapter = ObjectStorageReader
