"""
解决什么问题: 用同步 MilvusClient 封装 collection 初始化、写入、搜索、查询和清理
输入输出约定: 接收 LangChain Document 或向量列表，返回结构化字典列表
失败策略: 集合只在教程专用前缀内创建和删除；连接失败向上抛出给示例层处理
适用边界: 脚本、离线任务、CLI 工具；Web 服务内高并发调用建议改用异步客户端
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import sys
from typing import Any

from langchain_core.documents import Document

try:
    from pymilvus import DataType, MilvusClient
except ImportError as exc:  # pragma: no cover - 依赖缺失时给学习者明确提示
    raise RuntimeError("请先安装 pymilvus: uv add 'pymilvus[milvus-lite]>=3.0.0'") from exc

try:
    from .settings import MilvusSettings, load_settings
    from .vector_utils import l2_normalize, to_milvus_rows
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.settings import MilvusSettings, load_settings  # type: ignore[no-redef]
    from templates.vector_utils import l2_normalize, to_milvus_rows  # type: ignore[no-redef]


class SyncMilvusRepository:
    """面向教程的同步 Milvus 仓储。"""

    def __init__(self, settings: MilvusSettings | None = None) -> None:
        self.settings = settings or load_settings()
        kwargs: dict[str, Any] = {
            "uri": self.settings.uri,
            "timeout": self.settings.timeout,
        }
        if self.settings.token:
            kwargs["token"] = self.settings.token
        self.client = MilvusClient(**kwargs)

    def close(self) -> None:
        """关闭底层客户端连接。"""
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def ensure_collection(self, collection_name: str, *, reset: bool = False) -> None:
        """确保教程集合存在，reset=True 时先删除同名集合。"""
        if reset and self.client.has_collection(collection_name):
            self.client.drop_collection(collection_name)

        if self.client.has_collection(collection_name):
            return

        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.settings.dimension)
        schema.add_field("text", DataType.VARCHAR, max_length=1024)
        schema.add_field("source", DataType.VARCHAR, max_length=128)
        schema.add_field("chunk_no", DataType.INT64)

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )

        self.client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
            consistency_level="Strong",
        )

    def upsert_chunks(self, collection_name: str, chunks: Iterable[Document]) -> int:
        """写入或覆盖文档块，返回写入行数。"""
        rows = to_milvus_rows(chunks, dimension=self.settings.dimension)
        if not rows:
            return 0
        result = self.client.upsert(collection_name=collection_name, data=rows)
        return int(result.get("upsert_count") or result.get("insert_count") or len(rows))

    def search(
        self,
        collection_name: str,
        query_vector: Iterable[float],
        *,
        limit: int = 3,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """执行向量检索，可选按 source 做 scalar filter。"""
        vector = l2_normalize(query_vector, dimension=self.settings.dimension)
        filter_expr = f'source == "{source}"' if source else ""
        results = self.client.search(
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

    def query_by_source(self, collection_name: str, source: str) -> list[dict[str, Any]]:
        """按标量字段查询文档块。"""
        return self.client.query(
            collection_name=collection_name,
            filter=f'source == "{source}"',
            output_fields=["id", "text", "source", "chunk_no"],
            limit=100,
        )

    def delete_by_source(self, collection_name: str, source: str) -> int:
        """删除指定来源的数据，返回删除数量。"""
        result = self.client.delete(collection_name=collection_name, filter=f'source == "{source}"')
        return int(result.get("delete_count") or 0)

    def drop_collection(self, collection_name: str) -> None:
        """只删除显式传入的教程集合。"""
        if self.client.has_collection(collection_name):
            self.client.drop_collection(collection_name)


def _demo() -> None:
    try:
        from .vector_utils import build_demo_chunks
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from templates.vector_utils import build_demo_chunks  # type: ignore[no-redef]

    repo = SyncMilvusRepository()
    collection = repo.settings.collection_name("template_demo")
    try:
        repo.ensure_collection(collection, reset=True)
        inserted = repo.upsert_chunks(collection, build_demo_chunks(dimension=repo.settings.dimension))
        hits = repo.search(
            collection,
            [0.05, 0.08, 0.90, 0.14, 0.08, 0.04, 0.02, 0.0],
            source="milvus-guide",
        )
        print(f"inserted={inserted}")
        print(f"top_hit={hits[0]['id']} source={hits[0]['source']}")
    finally:
        repo.drop_collection(collection)
        repo.close()


if __name__ == "__main__":
    _demo()
