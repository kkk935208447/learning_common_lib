"""
目标: 在掌握同步基础后，用 AsyncMilvusClient 对已建好的 Milvus Lite collection 做并发检索
关键 API: MilvusClient, AsyncMilvusClient, asyncio.gather, asyncio.Semaphore
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/05_async_client/01_async_search_many.py
环境准备: 默认使用 Milvus Lite DB；也可设置 MILVUS_URI=http://localhost:19530 连接 Standalone
预期现象: 打印离线写入数量、3 个异步 query 的 top hit 和并发上限
生产提醒: 在线服务可以异步 search，但 collection/schema/index 通常由离线任务提前准备
"""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Iterable
from pathlib import Path

from pymilvus import AsyncMilvusClient, DataType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "8"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/async_search_many.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_async_search_many")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
CONCURRENCY_LIMIT = int(os.getenv("MILVUS_ASYNC_CONCURRENCY", "2"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """确保 Milvus Lite 的本机 gRPC 连接不会走 HTTP 代理。"""
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


def build_rows() -> list[dict[str, object]]:
    return [
        {
            "id": "doc-milvus-1",
            "text": "Milvus collection schema index",
            "source": "milvus-guide",
            "chunk_no": 1,
            "vector": l2_normalize([0.05, 0.08, 0.91, 0.13, 0.08, 0.04, 0.02, 0.0]),
        },
        {
            "id": "doc-python-1",
            "text": "Python asyncio service lifecycle",
            "source": "python-guide",
            "chunk_no": 1,
            "vector": l2_normalize([0.92, 0.11, 0.08, 0.03, 0.02, 0.01, 0.0, 0.0]),
        },
        {
            "id": "doc-rag-1",
            "text": "RAG query fanout should have a concurrency budget",
            "source": "rag-guide",
            "chunk_no": 1,
            "vector": l2_normalize([0.08, 0.10, 0.74, 0.35, 0.18, 0.05, 0.02, 0.0]),
        },
    ]


def build_sync_client() -> MilvusClient:
    if MILVUS_URI.endswith(".db"):
        ensure_local_no_proxy()
        Path(MILVUS_URI).parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, object] = {"uri": MILVUS_URI, "timeout": TIMEOUT_SECONDS}
    if MILVUS_TOKEN:
        kwargs["token"] = MILVUS_TOKEN
    return MilvusClient(**kwargs)


def prepare_collection() -> int:
    """用同步客户端准备数据，避免在在线请求路径里建索引。"""
    client = build_sync_client()
    try:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)

        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=DIMENSION)
        schema.add_field("text", DataType.VARCHAR, max_length=1024)
        schema.add_field("source", DataType.VARCHAR, max_length=128)
        schema.add_field("chunk_no", DataType.INT64)

        index_params = client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            schema=schema,
            index_params=index_params,
            consistency_level="Strong",
        )
        result = client.upsert(COLLECTION_NAME, data=build_rows())
        return int(result.get("upsert_count") or result.get("insert_count") or 0)
    finally:
        client.close()


def build_async_client() -> AsyncMilvusClient:
    if MILVUS_URI.endswith(".db"):
        ensure_local_no_proxy()
    kwargs: dict[str, object] = {"uri": MILVUS_URI, "timeout": TIMEOUT_SECONDS}
    if MILVUS_TOKEN:
        kwargs["token"] = MILVUS_TOKEN
    return AsyncMilvusClient(**kwargs)


async def search_one(client: AsyncMilvusClient, query_vector: Iterable[float]) -> dict[str, object]:
    result = await client.search(
        collection_name=COLLECTION_NAME,
        data=[l2_normalize(query_vector)],
        limit=2,
        output_fields=["text", "source"],
        search_params={"metric_type": "COSINE"},
    )
    top_hit = result[0][0]
    return {
        "id": top_hit["id"],
        "distance": round(float(top_hit["distance"]), 4),
        "source": top_hit["entity"]["source"],
    }


async def main() -> None:
    inserted = prepare_collection()
    try:
        async with build_async_client() as client:
            semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

            async def limited_search(query_vector: Iterable[float]) -> dict[str, object]:
                async with semaphore:
                    return await search_one(client, query_vector)

            queries = [
                [0.05, 0.08, 0.90, 0.14, 0.08, 0.04, 0.02, 0.0],
                [0.90, 0.12, 0.08, 0.03, 0.02, 0.01, 0.0, 0.0],
                [0.08, 0.10, 0.73, 0.36, 0.18, 0.05, 0.02, 0.0],
            ]
            results = await asyncio.gather(*(limited_search(query) for query in queries))
            print(f"offline_upsert_count={inserted}")
            print(f"async_query_count={len(results)}")
            print(f"concurrency_limit={CONCURRENCY_LIMIT}")
            for index, hit in enumerate(results, start=1):
                print(f"query_{index}_top_hit={hit}")
    finally:
        cleanup = build_sync_client()
        try:
            if cleanup.has_collection(COLLECTION_NAME):
                cleanup.drop_collection(COLLECTION_NAME)
        finally:
            cleanup.close()


if __name__ == "__main__":
    asyncio.run(main())
