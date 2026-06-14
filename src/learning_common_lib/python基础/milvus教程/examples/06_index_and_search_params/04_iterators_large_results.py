"""
目标: 使用 Milvus Lite 演示 query_iterator 和 search_iterator 分批读取大结果集
关键 API: query_iterator, search_iterator, batch_size, limit, close
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/06_index_and_search_params/04_iterators_large_results.py
环境准备: 默认使用 Milvus Lite DB；也可设置 MILVUS_URI=http://localhost:19530 连接 Standalone
预期现象: query_iterator 按 batch_size 分批返回标量查询结果，search_iterator 分批返回向量检索结果
生产提醒: iterator 必须 close；大结果集导出优先用 query_iterator，深分页搜索要控制 limit 和超时
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable
from pathlib import Path

from pymilvus import DataType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "4"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/iterators_large_results.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_iterators_large_results")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """Milvus Lite 会绑定本机端口，代理环境需要显式绕过。"""
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
    schema.add_field("category", DataType.VARCHAR, max_length=64)
    schema.add_field("chunk_no", DataType.INT64)

    index_params = client.prepare_index_params()
    index_params.add_index("vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(COLLECTION_NAME, schema=schema, index_params=index_params, consistency_level="Strong")

    rows = [
        {
            "id": f"milvus-{index}",
            "document_id": f"doc-milvus-{index // 2}",
            "category": "milvus",
            "chunk_no": index,
            "vector": l2_normalize([0.90 - index * 0.03, 0.10 + index * 0.03, 0.02, 0.01]),
        }
        for index in range(6)
    ]
    rows.extend(
        [
            {
                "id": "python-1",
                "document_id": "doc-python-1",
                "category": "python",
                "chunk_no": 1,
                "vector": l2_normalize([0.05, 0.90, 0.02, 0.01]),
            },
            {
                "id": "python-2",
                "document_id": "doc-python-1",
                "category": "python",
                "chunk_no": 2,
                "vector": l2_normalize([0.04, 0.88, 0.04, 0.01]),
            },
        ]
    )
    client.insert(COLLECTION_NAME, rows)
    client.flush(COLLECTION_NAME)


def collect_query_batches(client: MilvusClient) -> tuple[list[int], list[str]]:
    iterator = client.query_iterator(
        collection_name=COLLECTION_NAME,
        batch_size=2,
        limit=6,
        filter='category == "milvus"',
        output_fields=["id", "document_id", "chunk_no"],
    )
    batch_sizes: list[int] = []
    row_ids: list[str] = []
    try:
        while True:
            batch = iterator.next()
            if not batch:
                break
            batch_sizes.append(len(batch))
            row_ids.extend(str(row["id"]) for row in batch)
    finally:
        iterator.close()
    return batch_sizes, row_ids


def collect_search_batches(client: MilvusClient) -> tuple[list[int], list[str]]:
    iterator = client.search_iterator(
        collection_name=COLLECTION_NAME,
        data=[l2_normalize([0.90, 0.10, 0.02, 0.01])],
        batch_size=2,
        limit=4,
        filter='category == "milvus"',
        output_fields=["document_id", "chunk_no"],
        search_params={"metric_type": "COSINE"},
    )
    batch_sizes: list[int] = []
    hit_ids: list[str] = []
    try:
        while True:
            batch = iterator.next()
            if not batch:
                break
            batch_sizes.append(len(batch))
            hit_ids.extend(str(hit["id"]) for hit in batch)
    finally:
        iterator.close()
    return batch_sizes, hit_ids


def main() -> None:
    client = connect_client()
    try:
        recreate_collection(client)
        query_batch_sizes, query_ids = collect_query_batches(client)
        search_batch_sizes, search_ids = collect_search_batches(client)

        print(f"query_iterator_batch_sizes={query_batch_sizes}")
        print(f"query_iterator_ids={query_ids}")
        print(f"search_iterator_batch_sizes={search_batch_sizes}")
        print(f"search_iterator_ids={search_ids}")
        print("query_iterator 适合标量过滤导出；search_iterator 适合分批消费较大的向量检索 topK。")
        print("Milvus Lite 当前可能回退到 search_iterator v1，升级服务端后可使用新版 iterator。")
        assert sum(query_batch_sizes) == 6
        assert query_batch_sizes == [2, 2, 2]
        assert search_ids
        assert sum(search_batch_sizes) <= 4
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
