"""Search retrieval read port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

try:
    from .vector_read_port import RetrievalHit
except ImportError:
    from 最小可执行demo.ports.vector_read_port import RetrievalHit


class SearchReadPort(ABC):
    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalHit]:
        raise NotImplementedError
