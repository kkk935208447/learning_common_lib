"""
解决什么问题: 把索引管理、写入、检索封装成可复用的异步仓储骨架，适配 FastAPI/worker
输入输出约定: 输入文档 dict 和查询条件，输出原生 ES 响应或简化结果
失败策略: 不吞异常，向上层透传具体异常；客户端生命周期由调用层管理
适用边界: 异步服务；客户端应在应用启动时创建、关闭时释放，避免每请求新建
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk, async_scan

try:
    from .client_factory import create_async_client
    from .settings import load_settings
except ImportError:
    # 支持直接运行单个模板文件：回退到顶层包路径
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.client_factory import create_async_client  # type: ignore[no-redef]
    from templates.settings import load_settings  # type: ignore[no-redef]


class AsyncElasticsearchRepository:
    """围绕单个索引的异步仓储。客户端由外部注入并管理生命周期。"""

    def __init__(self, client: AsyncElasticsearch, index_name: str) -> None:
        self._client = client
        self._index = index_name

    async def ensure_index(self, mappings: dict[str, Any], settings: dict[str, Any] | None = None) -> None:
        """索引不存在则创建。"""
        if not await self._client.indices.exists(index=self._index):
            await self._client.indices.create(
                index=self._index, mappings=mappings, settings=settings or {}
            )

    async def index_document(self, doc_id: str, document: dict[str, Any], refresh: bool = False) -> str:
        resp = await self._client.index(
            index=self._index, id=doc_id, document=document, refresh=refresh
        )
        return resp["result"]

    async def bulk_index(self, items: Iterable[tuple[str, dict[str, Any]]], refresh: bool = False) -> int:
        """批量写入；async_bulk 需要一个异步生成器产出 action。"""

        async def actions() -> AsyncIterator[dict[str, Any]]:
            for doc_id, document in items:
                yield {"_index": self._index, "_id": doc_id, "_source": document}

        success, _ = await async_bulk(self._client, actions(), refresh=refresh)
        return success

    async def get_document(self, doc_id: str) -> dict[str, Any] | None:
        resp = await self._client.options(ignore_status=404).get(index=self._index, id=doc_id)
        if resp.meta.status == 404:
            return None
        return resp["_source"]

    async def search(self, query: dict[str, Any], size: int = 10, **kwargs: Any) -> list[dict[str, Any]]:
        resp = await self._client.search(index=self._index, query=query, size=size, **kwargs)
        return [
            {"id": hit["_id"], "score": hit["_score"], "source": hit["_source"]}
            for hit in resp["hits"]["hits"]
        ]

    async def scan_all(self, query: dict[str, Any], page_size: int = 500) -> AsyncIterator[dict[str, Any]]:
        """异步遍历全部匹配文档。"""
        async for hit in async_scan(
            self._client, index=self._index, query={"query": query}, size=page_size
        ):
            yield hit["_source"]

    async def delete_document(self, doc_id: str, refresh: bool = False) -> bool:
        resp = await self._client.options(ignore_status=404).delete(
            index=self._index, id=doc_id, refresh=refresh
        )
        return resp.meta.status != 404


async def _demo() -> None:
    settings = load_settings()
    index = settings.index_name("async_repo_demo")
    client = create_async_client(settings)
    repo = AsyncElasticsearchRepository(client, index)
    try:
        await client.options(ignore_status=404).indices.delete(index=index)
        await repo.ensure_index(mappings={"properties": {"title": {"type": "text"}}})
        await repo.bulk_index([("1", {"title": "async one"}), ("2", {"title": "async two"})], refresh=True)
        hits = await repo.search({"match": {"title": "async"}})
        print(f"index={index} search_hits={len(hits)}")
    finally:
        await client.options(ignore_status=404).indices.delete(index=index)
        await client.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_demo())
