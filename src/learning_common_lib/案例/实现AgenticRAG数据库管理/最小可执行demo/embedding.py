"""Deterministic embedding mock so demo data can be rebuilt repeatably."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

try:
    from .config import get_settings
except ImportError:
    from config import get_settings


# embedding 接口和实现拆开，是为了让 index 流程不直接依赖某个具体模型。
class BaseEmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        # 批量接口让 IndexPipelineService 不需要关心具体 provider 是否支持并行优化。
        raise NotImplementedError


class DeterministicEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, dim: int | None = None) -> None:
        # 维度默认来自配置，方便在 README 和代码里保持一致。
        self.dim = dim or get_settings().embedding_dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            # 对相同文本永远产出相同向量，便于 demo 重放、Janitor 重建和测试断言。
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vector = []
            for idx in range(self.dim):
                # 这里只取 digest 的前 dim 个字节，目标是稳定而不是语义质量。
                byte = digest[idx]
                vector.append(round(byte / 255.0, 6))
            vectors.append(vector)
        return vectors
