"""
目标: 用 Milvus Lite 演示异步客户端在服务生命周期内复用连接
关键 API: MilvusClient, AsyncMilvusClient, async context manager, asyncio.Semaphore
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/05_async_client/02_async_lifecycle_policy.py
环境准备: 默认使用 Milvus Lite DB；也可设置 MILVUS_URI=http://localhost:19530 连接 Standalone
预期现象: 同步客户端完成离线建库，异步客户端复用连接执行 3 个并发检索
生产提醒: 离线索引构建和在线异步检索应分层；不要在每个请求里创建 AsyncMilvusClient
"""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Iterable
from pathlib import Path

from pymilvus import AsyncMilvusClient, DataType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "8"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/async_lifecycle_policy.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_async_lifecycle_policy")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
CONCURRENCY_LIMIT = int(os.getenv("MILVUS_ASYNC_CONCURRENCY", "2"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """Milvus Lite 使用本机 gRPC 端口，代理变量必须绕过 127.0.0.1。"""
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
            "id": "doc-milvus-async",
            "text": "AsyncMilvusClient 适合在线服务并发检索",
            "source": "milvus-guide",
            "vector": l2_normalize([0.05, 0.08, 0.91, 0.13, 0.08, 0.04, 0.02, 0.0]),
        },
        {
            "id": "doc-python-lifespan",
            "text": "FastAPI lifespan 可以管理客户端启动和关闭",
            "source": "python-guide",
            "vector": l2_normalize([0.88, 0.20, 0.09, 0.04, 0.02, 0.01, 0.0, 0.0]),
        },
        {
            "id": "doc-rag-batch",
            "text": "批量查询需要用 Semaphore 限制并发",
            "source": "rag-guide",
            "vector": l2_normalize([0.12, 0.10, 0.76, 0.32, 0.14, 0.05, 0.02, 0.0]),
        },
    ]


def sync_prepare_collection() -> None:
    """用同步客户端准备 collection，模拟离线索引构建任务。"""
    if MILVUS_URI.endswith(".db"):
        ensure_local_no_proxy()
        Path(MILVUS_URI).parent.mkdir(parents=True, exist_ok=True)

    kwargs: dict[str, object] = {"uri": MILVUS_URI, "timeout": TIMEOUT_SECONDS}
    if MILVUS_TOKEN:
        kwargs["token"] = MILVUS_TOKEN

    client = MilvusClient(**kwargs)
    try:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)

        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=DIMENSION)
        schema.add_field("text", DataType.VARCHAR, max_length=1024)
        schema.add_field("source", DataType.VARCHAR, max_length=128)

        index_params = client.prepare_index_params()
        index_params.add_index("vector", index_type="AUTOINDEX", metric_type="COSINE")

        client.create_collection(
            collection_name=COLLECTION_NAME,
            schema=schema,
            index_params=index_params,
            consistency_level="Strong",
        )
        insert_result = client.insert(COLLECTION_NAME, build_rows())
        print(f"offline_prepare_inserted={insert_result.get('insert_count')}")
    finally:
        client.close()


def build_async_client() -> AsyncMilvusClient:
    if MILVUS_URI.endswith(".db"):
        ensure_local_no_proxy()
    kwargs: dict[str, object] = {"uri": MILVUS_URI, "timeout": TIMEOUT_SECONDS}
    if MILVUS_TOKEN:
        kwargs["token"] = MILVUS_TOKEN
    return AsyncMilvusClient(**kwargs)


async def online_search(client: AsyncMilvusClient, query_vector: Iterable[float]) -> dict[str, object]:
    result = await client.search(
        collection_name=COLLECTION_NAME,
        data=[l2_normalize(query_vector)],
        limit=1,
        output_fields=["text", "source"],
        search_params={"metric_type": "COSINE"},
    )
    hit = result[0][0]
    return {
        "id": hit["id"],
        "score": round(float(hit["distance"]), 4),
        "source": hit["entity"]["source"],
    }


async def main() -> None:
    sync_prepare_collection()
    try:
        async with build_async_client() as client:
            semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

            async def limited_search(query_vector: Iterable[float]) -> dict[str, object]:
                async with semaphore:
                    return await online_search(client, query_vector)

            results = await asyncio.gather(
                limited_search([0.05, 0.08, 0.90, 0.14, 0.08, 0.04, 0.02, 0.0]),
                limited_search([0.90, 0.18, 0.08, 0.04, 0.02, 0.01, 0.0, 0.0]),
                limited_search([0.12, 0.10, 0.75, 0.33, 0.14, 0.05, 0.02, 0.0]),
            )
            print(f"async_client_scope=application_lifespan")
            print(f"concurrency_limit={CONCURRENCY_LIMIT}")
            print(f"online_search_count={len(results)}")
            for index, item in enumerate(results, start=1):
                print(f"query_{index}_top_hit={item}")
    finally:
        cleanup = MilvusClient(uri=MILVUS_URI, token=MILVUS_TOKEN or None, timeout=TIMEOUT_SECONDS)
        try:
            if cleanup.has_collection(COLLECTION_NAME):
                cleanup.drop_collection(COLLECTION_NAME)
        finally:
            cleanup.close()


if __name__ == "__main__":
    asyncio.run(main())
