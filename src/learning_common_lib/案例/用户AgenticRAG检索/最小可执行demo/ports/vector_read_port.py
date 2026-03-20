"""Vector retrieval read port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypedDict


class RetrievalHit(TypedDict, total=False):
    chunk_uid: str
    version_id: int
    document_id: int | None
    external_doc_key: str | None
    source_type: str
    score: float
    content: str
    metadata: dict[str, Any]
    locator: dict[str, Any]


class VectorReadPort(ABC):
    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalHit]:
        raise NotImplementedError
