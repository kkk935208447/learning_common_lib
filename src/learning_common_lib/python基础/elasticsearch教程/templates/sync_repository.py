"""
解决什么问题: 把索引管理、写入、检索、分页封装成可复用的同步仓储骨架
输入输出约定: 输入文档 dict 和查询条件，输出原生 ES 响应或简化结果
失败策略: 不吞异常，向上层透传 NotFoundError/ConflictError 等具体异常
适用边界: 教程和中小服务；高并发或多索引路由场景需扩展为按需路由和连接池调优
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable, Iterator

from elasticsearch import Elasticsearch, helpers

try:
    from .client_factory import create_client
    from .settings import load_settings
except ImportError:
    # 支持直接运行单个模板文件：回退到顶层包路径
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.client_factory import create_client  # type: ignore[no-redef]
    from templates.settings import load_settings  # type: ignore[no-redef]


class SyncElasticsearchRepository:
    """围绕单个索引的同步仓储。索引名建议来自 Settings.index_name。"""

    def __init__(self, client: Elasticsearch, index_name: str) -> None:
        self._client = client
        self._index = index_name

    def ensure_index(self, mappings: dict[str, Any], settings: dict[str, Any] | None = None) -> None:
        """索引不存在则创建；已存在则保持不变，不强行重建。"""
        if not self._client.indices.exists(index=self._index):
            self._client.indices.create(index=self._index, mappings=mappings, settings=settings or {})

    def index_document(self, doc_id: str, document: dict[str, Any], refresh: bool = False) -> str:
        """写入或覆盖单条文档，返回 result（created/updated）。"""
        resp = self._client.index(
            index=self._index, id=doc_id, document=document, refresh=refresh
        )
        return resp["result"]

    def bulk_index(self, items: Iterable[tuple[str, dict[str, Any]]], refresh: bool = False) -> int:
        """批量写入，items 为 (doc_id, document) 序列，返回成功条数。"""

        def actions() -> Iterator[dict[str, Any]]:
            for doc_id, document in items:
                yield {"_index": self._index, "_id": doc_id, "_source": document}

        success, _ = helpers.bulk(self._client, actions(), refresh=refresh)
        return success

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """读取文档，不存在返回 None 而非抛 404。"""
        resp = self._client.options(ignore_status=404).get(index=self._index, id=doc_id)
        if resp.meta.status == 404:
            return None
        return resp["_source"]

    def search(self, query: dict[str, Any], size: int = 10, **kwargs: Any) -> list[dict[str, Any]]:
        """执行查询，返回 [{id, score, source}] 简化结果。"""
        resp = self._client.search(index=self._index, query=query, size=size, **kwargs)
        return [
            {"id": hit["_id"], "score": hit["_score"], "source": hit["_source"]}
            for hit in resp["hits"]["hits"]
        ]

    def scan_all(self, query: dict[str, Any], page_size: int = 500) -> Iterator[dict[str, Any]]:
        """用 helpers.scan 遍历全部匹配文档，内部基于 PIT/scroll，适合导出。"""
        for hit in helpers.scan(
            self._client, index=self._index, query={"query": query}, size=page_size
        ):
            yield hit["_source"]

    def delete_document(self, doc_id: str, refresh: bool = False) -> bool:
        """删除文档，不存在返回 False。"""
        resp = self._client.options(ignore_status=404).delete(
            index=self._index, id=doc_id, refresh=refresh
        )
        return resp.meta.status != 404


def _demo() -> None:
    settings = load_settings()
    index = settings.index_name("repo_demo")
    client = create_client(settings)
    repo = SyncElasticsearchRepository(client, index)
    try:
        client.options(ignore_status=404).indices.delete(index=index)
        repo.ensure_index(mappings={"properties": {"title": {"type": "text"}}})
        repo.bulk_index([("1", {"title": "demo one"}), ("2", {"title": "demo two"})], refresh=True)
        hits = repo.search({"match": {"title": "demo"}})
        print(f"index={index} search_hits={len(hits)}")
        print(f"get id=1 -> {repo.get_document('1')}")
    finally:
        client.options(ignore_status=404).indices.delete(index=index)
        client.close()


if __name__ == "__main__":
    _demo()
