"""
目标: 使用 Milvus Lite 演示 group_by_field 对同一文档的多个 chunk 做检索去重
关键 API: search(group_by_field=...), group_size, strict_group_size, output_fields
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/06_index_and_search_params/05_grouping_search.py
环境准备: 默认使用 Milvus Lite DB；也可设置 MILVUS_URI=http://localhost:19530 连接 Standalone
预期现象: 普通搜索会返回同一 document_id 的多个 chunk，grouping search 每个 document_id 只返回一个代表 chunk
生产提醒: RAG 通常需要按 document_id 去重，否则同一文档的相邻 chunk 会挤占上下文窗口
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable
from pathlib import Path

from pymilvus import DataType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "4"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/grouping_search.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_grouping_search")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """Milvus Lite 本机 gRPC 连接需要绕过代理。"""
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def l2_normalize(vector: Iterable[float]) -> list[float]:
    values = [float(item) for item in vector]
    norm = math.sqrt(sum(item * item for item in values))
    if len(values) != DIMENSION or norm == 0:
        raise ValueError("向量维度错误或为零向量")
    return [item / norm for item in values]


def connect_client() -> MilvusClient:
    if MILVUS_URI.endswith(".db"):
        ensure_local_no_proxy()
        Path(MILVUS_URI).parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, object] = {"uri": MILVUS_URI, "timeout": TIMEOUT_SECONDS}
    if MILVUS_TOKEN:
        kwargs["token"] = MILVUS_TOKEN
    return MilvusClient(**kwargs)


def recreate_collection(client: MilvusClient) -> None:
    if client.has_collection(COLLECTION_NAME):
        client.drop_collection(COLLECTION_NAME)

    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=DIMENSION)
    schema.add_field("document_id", DataType.VARCHAR, max_length=128)
    schema.add_field("chunk_no", DataType.INT64)
    schema.add_field("text", DataType.VARCHAR, max_length=512)

    index_params = client.prepare_index_params()
    index_params.add_index("vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(COLLECTION_NAME, schema=schema, index_params=index_params, consistency_level="Strong")
    client.insert(
        COLLECTION_NAME,
        [
            {
                "id": "doc-a-chunk-1",
                "document_id": "doc-a",
                "chunk_no": 1,
                "text": "Milvus collection schema",
                "vector": l2_normalize([0.93, 0.08, 0.02, 0.01]),
            },
            {
                "id": "doc-a-chunk-2",
                "document_id": "doc-a",
                "chunk_no": 2,
                "text": "Milvus index search params",
                "vector": l2_normalize([0.90, 0.10, 0.02, 0.01]),
            },
            {
                "id": "doc-b-chunk-1",
                "document_id": "doc-b",
                "chunk_no": 1,
                "text": "Milvus partition alias",
                "vector": l2_normalize([0.78, 0.28, 0.06, 0.01]),
            },
            {
                "id": "doc-c-chunk-1",
                "document_id": "doc-c",
                "chunk_no": 1,
                "text": "Python async lifecycle",
                "vector": l2_normalize([0.05, 0.91, 0.03, 0.01]),
            },
        ],
    )


def document_ids(results: list[dict]) -> list[str]:
    return [str(hit["entity"]["document_id"]) for hit in results]


def main() -> None:
    client = connect_client()
    try:
        recreate_collection(client)
        query = [l2_normalize([0.91, 0.09, 0.02, 0.01])]
        plain_results = client.search(
            collection_name=COLLECTION_NAME,
            data=query,
            limit=4,
            output_fields=["document_id", "chunk_no", "text"],
            search_params={"metric_type": "COSINE"},
        )
        grouped_results = client.search(
            collection_name=COLLECTION_NAME,
            data=query,
            limit=3,
            group_by_field="document_id",
            group_size=1,
            strict_group_size=True,
            output_fields=["document_id", "chunk_no", "text"],
            search_params={"metric_type": "COSINE"},
        )

        plain_doc_ids = document_ids(plain_results[0])
        grouped_doc_ids = document_ids(grouped_results[0])
        print(f"plain_doc_ids={plain_doc_ids}")
        print(f"grouped_doc_ids={grouped_doc_ids}")
        print(f"grouped_top_entities={[hit['entity'] for hit in grouped_results[0]]}")
        print("group_by_field 的 limit 表示返回多少个组，group_size 表示每组返回多少个实体。")
        assert plain_doc_ids.count("doc-a") == 2
        assert len(grouped_doc_ids) == len(set(grouped_doc_ids))
        assert grouped_doc_ids[0] == "doc-a"
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
