"""
目标: 使用 Milvus Lite 演示 collection 级和请求级 consistency_level
关键 API: create_collection(consistency_level=...), query(consistency_level=...)
本例重点参数:
- create_collection(consistency_level): 设置集合默认一致性，影响后续读请求默认行为。
- query(consistency_level): 单次请求覆盖默认一致性，用来排查“写完立刻读不到”的链路。
- 常见值: Strong、Bounded、Eventually、Session；生产需在写后读准确性和吞吐之间取舍。
流程索引: roadmap.md#milvus-工程使用流程
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/04_errors_and_recovery/03_consistency_levels.py
环境准备: 默认使用 Milvus Lite DB；也可设置 MILVUS_URI=http://localhost:19530 连接 Standalone
预期现象: 同一批数据在 Strong、Bounded、Eventually、Session 四种请求级一致性下都能查询到
生产提醒: Strong 更适合写后立刻读的验证链路；Bounded 是 Milvus 默认值，Eventually 更偏吞吐和可用性
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable
from pathlib import Path

from pymilvus import DataType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "8"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/consistency_levels.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_consistency_levels")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"
CONSISTENCY_LEVELS = ("Strong", "Bounded", "Eventually", "Session")


def ensure_local_no_proxy() -> None:
    """避免 Milvus Lite 的本机 gRPC 连接被 HTTP 代理拦截。"""
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
    schema.add_field("source", DataType.VARCHAR, max_length=128)
    schema.add_field("text", DataType.VARCHAR, max_length=1024)

    index_params = client.prepare_index_params()
    index_params.add_index("vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
        consistency_level="Strong",
    )
    client.insert(
        COLLECTION_NAME,
        [
            {
                "id": "doc-consistency-strong",
                "source": "milvus-guide",
                "text": "Strong 适合写完立刻验证的导入链路",
                "vector": l2_normalize([0.05, 0.08, 0.91, 0.13, 0.08, 0.04, 0.02, 0.0]),
            },
            {
                "id": "doc-consistency-bounded",
                "source": "milvus-guide",
                "text": "Bounded 是 Milvus 默认的一致性级别",
                "vector": l2_normalize([0.04, 0.07, 0.88, 0.18, 0.10, 0.05, 0.02, 0.0]),
            },
        ],
    )
    client.flush(COLLECTION_NAME)


def main() -> None:
    client = connect_client()
    try:
        recreate_collection(client)
        level_counts: dict[str, int] = {}
        for level in CONSISTENCY_LEVELS:
            rows = client.query(
                collection_name=COLLECTION_NAME,
                filter='source == "milvus-guide"',
                output_fields=["id", "source"],
                limit=10,
                consistency_level=level,
            )
            level_counts[level] = len(rows)
            print(f"{level}_query_count={len(rows)}")

        print("Strong/Bounded/Eventually/Session 可以在 collection 创建时设默认值，也可以在单次 query/search 覆盖。")
        print("本地 Lite 是单进程环境，不容易复现分布式副本延迟；生产环境仍要按写后读要求选择级别。")
        assert set(level_counts) == set(CONSISTENCY_LEVELS)
        assert all(count == 2 for count in level_counts.values())
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
