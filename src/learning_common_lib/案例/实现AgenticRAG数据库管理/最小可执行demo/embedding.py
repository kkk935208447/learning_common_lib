from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

try:
    from .config import get_settings
except ImportError:
    from config import get_settings


class BaseEmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class DeterministicEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or get_settings().embedding_dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vector = []
            for idx in range(self.dim):
                byte = digest[idx]
                vector.append(round(byte / 255.0, 6))
            vectors.append(vector)
        return vectors
