"""
目标: 使用 Milvus Lite 真实演示 partition 的创建、写入、限定检索和清理
关键 API: create_partition, list_partitions, insert(partition_name=...), search(partition_names=...), release_collection, drop_partition
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/07_partitions_aliases/01_partition_lifecycle.py
环境准备: 默认使用 Milvus Lite DB；也可设置 MILVUS_URI=http://localhost:19530 连接 Standalone
预期现象: 同一个 collection 下创建 tenant_a/tenant_b，检索时只命中指定 partition
生产提醒: partition 适合少量粗粒度隔离；高频权限和来源过滤优先用 scalar filter
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable
from pathlib import Path

from pymilvus import DataType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "8"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/partition_lifecycle.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_partition_lifecycle")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
PARTITION_A = "tenant_a"
PARTITION_B = "tenant_b"
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
    schema.add_field("text", DataType.VARCHAR, max_length=1024)
    schema.add_field("tenant_id", DataType.VARCHAR, max_length=64)

    index_params = client.prepare_index_params()
    index_params.add_index("vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
        consistency_level="Strong",
    )


def insert_partition_rows(client: MilvusClient) -> None:
    client.create_partition(collection_name=COLLECTION_NAME, partition_name=PARTITION_A)
    client.create_partition(collection_name=COLLECTION_NAME, partition_name=PARTITION_B)
    # 中间状态：刚建好 partition、还没写数据时，集合里已经能看到三个分区（含默认 _default）
    print(f"创建分区后 partitions={client.list_partitions(collection_name=COLLECTION_NAME)}")
    client.insert(
        collection_name=COLLECTION_NAME,
        partition_name=PARTITION_A,
        data=[
            {
                "id": "tenant-a-milvus",
                "text": "tenant_a 的 Milvus 文档",
                "tenant_id": "tenant_a",
                "vector": l2_normalize([0.05, 0.08, 0.91, 0.13, 0.08, 0.04, 0.02, 0.0]),
            }
        ],
    )
    client.insert(
        collection_name=COLLECTION_NAME,
        partition_name=PARTITION_B,
        data=[
            {
                "id": "tenant-b-python",
                "text": "tenant_b 的 Python 文档",
                "tenant_id": "tenant_b",
                "vector": l2_normalize([0.90, 0.12, 0.08, 0.04, 0.02, 0.01, 0.0, 0.0]),
            }
        ],
    )


def main() -> None:
    client = connect_client()
    try:
        recreate_collection(client)
        insert_partition_rows(client)
        partitions = client.list_partitions(collection_name=COLLECTION_NAME)
        results = client.search(
            collection_name=COLLECTION_NAME,
            data=[l2_normalize([0.05, 0.08, 0.90, 0.14, 0.08, 0.04, 0.02, 0.0])],
            partition_names=[PARTITION_A],
            filter='tenant_id == "tenant_a"',
            limit=2,
            output_fields=["text", "tenant_id"],
            search_params={"metric_type": "COSINE"},
        )
        all_rows = client.query(COLLECTION_NAME, filter='tenant_id != ""', output_fields=["id", "tenant_id"], limit=10)

        print(f"partitions={partitions}")
        print(f"all_row_count={len(all_rows)}")
        print(f"tenant_a_top_hit={results[0][0]['id']}")
        print(f"tenant_a_top_entity={results[0][0]['entity']}")
        print("partition_names 用于物理分区缩小搜索范围，filter 用于业务字段过滤。")

        # Standalone 上 partition 被 load 时不能直接 drop。release_collection 在 Lite 和 Standalone 都支持，
        # 比 release_partitions（Lite 不支持）更可移植；释放后即可安全删除 partition。
        client.release_collection(collection_name=COLLECTION_NAME)
        client.drop_partition(collection_name=COLLECTION_NAME, partition_name=PARTITION_B)
        print(f"after_drop_partition={client.list_partitions(collection_name=COLLECTION_NAME)}")
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
