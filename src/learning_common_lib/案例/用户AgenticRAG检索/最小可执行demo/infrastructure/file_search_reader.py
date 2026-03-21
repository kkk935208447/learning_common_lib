"""File-based full-text reader that consumes the upstream demo search projections."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

try:
    from ..ports.search_read_port import SearchReadPort
    from ..ports.vector_read_port import RetrievalHit
    from ._projection_utils import bm25_lite_score, load_json_records
    from .settings import get_settings
except ImportError:
    from 最小可执行demo.ports.search_read_port import SearchReadPort
    from 最小可执行demo.ports.vector_read_port import RetrievalHit
    from 最小可执行demo.infrastructure._projection_utils import bm25_lite_score, load_json_records
    from 最小可执行demo.infrastructure.settings import get_settings


class FileSearchReader(SearchReadPort):
    """Reads ES-like projection files written by the upstream index pipeline."""

    def __init__(self, root_dir: Path | None = None) -> None:
        settings = get_settings()
        self.root_dir = root_dir or (settings.upstream_runtime_dir / "search_store")
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.default_kb_code = settings.default_kb_code

    async def search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalHit]:
        filters = filters or {}
        allowed_version_ids = set(filters.get("allowed_version_ids") or [])
        if not allowed_version_ids:
            return []
        records = await asyncio.to_thread(load_json_records, self.root_dir)
        doc_by_version = filters.get("document_by_version") or {}
        key_by_version = filters.get("external_doc_key_by_version") or {}
        storage_by_version = filters.get("storage_key_by_version") or {}

        hits: list[RetrievalHit] = []
        for record in records:
            version_id = int(record.get("version_id") or 0)
            if version_id not in allowed_version_ids:
                continue
            content = str(record.get("content") or "")
            chunk_uid = str(record.get("chunk_uid") or "")
            if not chunk_uid:
                continue
            score = bm25_lite_score(query, content)
            hits.append(
                {
                    "chunk_uid": chunk_uid,
                    "version_id": version_id,
                    "document_id": doc_by_version.get(version_id),
                    "external_doc_key": key_by_version.get(version_id),
                    "source_type": "ES",
                    "score": round(score, 6),
                    "content": content,
                    "metadata": dict(record.get("metadata") or {}),
                    "locator": {
                        "kb_code": filters.get("kb_code", self.default_kb_code),
                        "version_id": version_id,
                        "document_id": doc_by_version.get(version_id),
                        "external_doc_key": key_by_version.get(version_id),
                        "storage_key": storage_by_version.get(version_id),
                        "chunk_uid": chunk_uid,
                    },
                }
            )

        hits.sort(key=lambda item: item["score"], reverse=True)
        return hits[:top_k]
