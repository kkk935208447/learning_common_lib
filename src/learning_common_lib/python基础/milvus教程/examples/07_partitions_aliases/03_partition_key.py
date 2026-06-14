"""
目标: 使用 Milvus Lite 演示 partition key 字段的 schema 声明和租户过滤
关键 API: add_field(is_partition_key=True), create_collection, query, search(filter=...)
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/07_partitions_aliases/03_partition_key.py
环境准备: 默认使用 Milvus Lite DB；也可设置 MILVUS_URI=http://localhost:19530 连接 Standalone
预期现象: tenant_id 字段在 schema 中标记为 partition key，按 tenant_id 查询和搜索只返回目标租户
生产提醒: partition key 适合多租户或高基数字段的自动分区路由；手动 partition 适合少量粗粒度分区
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable
from pathlib import Path

from pymilvus import DataType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "4"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/partition_key.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_partition_key")
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
    schema.add_field("tenant_id", DataType.VARCHAR, max_length=64, is_partition_key=True)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=DIMENSION)
    schema.add_field("text", DataType.VARCHAR, max_length=512)

    index_params = client.prepare_index_params()
    index_params.add_index("vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(COLLECTION_NAME, schema=schema, index_params=index_params, consistency_level="Strong")
    client.insert(
        COLLECTION_NAME,
        [
            {
                "id": "tenant-a-milvus",
                "tenant_id": "tenant-a",
                "text": "tenant-a 的 Milvus 检索文档",
                "vector": l2_normalize([0.90, 0.10, 0.02, 0.01]),
            },
            {
                "id": "tenant-b-python",
                "tenant_id": "tenant-b",
                "text": "tenant-b 的 Python 异步文档",
                "vector": l2_normalize([0.05, 0.91, 0.02, 0.01]),
            },
        ],
    )


def partition_key_fields(client: MilvusClient) -> list[str]:
    description = client.describe_collection(COLLECTION_NAME)
    return [field["name"] for field in description["fields"] if field.get("is_partition_key")]


def main() -> None:
    client = connect_client()
    try:
        recreate_collection(client)
        tenant_rows = client.query(
            collection_name=COLLECTION_NAME,
            filter='tenant_id == "tenant-a"',
            output_fields=["id", "tenant_id"],
            limit=10,
        )
        tenant_hits = client.search(
            collection_name=COLLECTION_NAME,
            data=[l2_normalize([0.90, 0.10, 0.02, 0.01])],
            filter='tenant_id == "tenant-a"',
            limit=2,
            output_fields=["tenant_id", "text"],
            search_params={"metric_type": "COSINE"},
        )
        fields = partition_key_fields(client)

        print(f"partition_key_fields={fields}")
        print(f"tenant_a_query_rows={tenant_rows}")
        print(f"tenant_a_search_ids={[hit['id'] for hit in tenant_hits[0]]}")
        print("partition key 由 Milvus 根据字段值自动路由；查询时仍建议显式带 tenant_id filter。")
        assert fields == ["tenant_id"]
        assert [row["tenant_id"] for row in tenant_rows] == ["tenant-a"]
        assert [hit["id"] for hit in tenant_hits[0]] == ["tenant-a-milvus"]
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
