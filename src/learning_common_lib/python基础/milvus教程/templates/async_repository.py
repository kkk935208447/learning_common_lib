"""
解决什么问题: 用 AsyncMilvusClient 封装异步向量检索的最小生产骨架
输入输出约定: 在 async with 生命周期内创建连接，所有 Milvus 操作都需要 await
失败策略: 连接、超时、Milvus 服务错误不吞掉，由调用层统一映射为业务错误
适用边界: FastAPI、异步 worker、批量并发检索；基础脚本优先用同步客户端降低认知负担
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path
import sys
from typing import Any

try:
    from pymilvus import AsyncMilvusClient
except ImportError as exc:  # pragma: no cover - 依赖缺失时给学习者明确提示
    raise RuntimeError("请先安装 pymilvus: uv add 'pymilvus[milvus-lite]>=3.0.0'") from exc

try:
    from .settings import MilvusSettings, load_settings
    from .vector_utils import l2_normalize
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.settings import MilvusSettings, load_settings  # type: ignore[no-redef]
    from templates.vector_utils import l2_normalize  # type: ignore[no-redef]


class AsyncMilvusRepository:
    """面向异步服务的 Milvus 仓储。"""

    def __init__(self, settings: MilvusSettings | None = None) -> None:
        self.settings = settings or load_settings()
        kwargs: dict[str, Any] = {
            "uri": self.settings.uri,
            "timeout": self.settings.timeout,
        }
        if self.settings.token:
            kwargs["token"] = self.settings.token
        self.client = AsyncMilvusClient(**kwargs)

    async def __aenter__(self) -> "AsyncMilvusRepository":
        await self.client.__aenter__()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.client.__aexit__(exc_type, exc, tb)

    async def search(
        self,
        collection_name: str,
        query_vector: Iterable[float],
        *,
        limit: int = 3,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """异步执行向量检索。"""
        vector = l2_normalize(query_vector, dimension=self.settings.dimension)
        filter_expr = f'source == "{source}"' if source else ""
        results = await self.client.search(
            collection_name=collection_name,
            data=[vector],
            filter=filter_expr,
            limit=limit,
            output_fields=["text", "source", "chunk_no"],
            search_params={"metric_type": "COSINE"},
        )
        return [
            {
                "id": hit["id"],
                "score": float(hit["distance"]),
                "text": hit["entity"]["text"],
                "source": hit["entity"]["source"],
                "chunk_no": hit["entity"]["chunk_no"],
            }
            for hit in results[0]
        ]

    async def search_many(
        self,
        collection_name: str,
        queries: Iterable[Iterable[float]],
        *,
        limit: int = 2,
        concurrency: int = 4,
    ) -> list[list[dict[str, Any]]]:
        """带并发上限的批量异步搜索。"""
        semaphore = asyncio.Semaphore(concurrency)

        async def run_one(query: Iterable[float]) -> list[dict[str, Any]]:
            async with semaphore:
                return await self.search(collection_name, query, limit=limit)

        return await asyncio.gather(*(run_one(query) for query in queries))

    async def drop_collection(self, collection_name: str) -> None:
        """删除异步示例集合。"""
        if await self.client.has_collection(collection_name):
            await self.client.drop_collection(collection_name)


async def _demo() -> None:
    try:
        from .sync_repository import SyncMilvusRepository
        from .vector_utils import build_demo_chunks
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from templates.sync_repository import SyncMilvusRepository  # type: ignore[no-redef]
        from templates.vector_utils import build_demo_chunks  # type: ignore[no-redef]

    sync_repo = SyncMilvusRepository()
    collection = sync_repo.settings.collection_name("async_template_demo")
    try:
        sync_repo.ensure_collection(collection, reset=True)
        inserted = sync_repo.upsert_chunks(
            collection,
            build_demo_chunks(dimension=sync_repo.settings.dimension),
        )

        async with AsyncMilvusRepository(settings=sync_repo.settings) as repo:
            results = await repo.search_many(
                collection,
                [
                    [0.05, 0.08, 0.90, 0.14, 0.08, 0.04, 0.02, 0.0],
                    [0.90, 0.12, 0.08, 0.03, 0.02, 0.01, 0.0, 0.0],
                ],
            )
            print(f"offline_inserted={inserted}")
            print(f"async_search_batches={len(results)} first_batch_hits={len(results[0])}")
    finally:
        sync_repo.drop_collection(collection)
        sync_repo.close()


if __name__ == "__main__":
    asyncio.run(_demo())
