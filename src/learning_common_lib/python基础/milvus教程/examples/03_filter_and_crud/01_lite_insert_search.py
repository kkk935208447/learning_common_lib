"""
目标: 使用 Milvus Lite 或 Standalone 跑通 create_collection → upsert → search → drop
关键 API: MilvusClient, create_collection, upsert, search, drop_collection
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/03_filter_and_crud/01_lite_insert_search.py
环境准备: 默认使用 .milvus_tutorial/lite_insert_search.db；也可设置 MILVUS_URI=http://localhost:19530
预期现象: 打印写入数量、top hit 和命中文本
生产提醒: 本示例会删除教程专用集合 learning_milvus_lite_insert_search，不会清理其他集合
"""

import math
import os
from pathlib import Path
from typing import Iterable

from pymilvus import DataType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "8"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/lite_insert_search.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_lite_insert_search")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """Milvus Lite 会监听本机随机端口，必须绕过 HTTP 代理。"""
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def l2_normalize(vector: Iterable[float]) -> list[float]:
    values = [float(item) for item in vector]
    if len(values) != DIMENSION:
        raise ValueError(f"向量维度不匹配: expected={DIMENSION}, actual={len(values)}")
    norm = math.sqrt(sum(item * item for item in values))
    if norm == 0:
        raise ValueError("零向量不能归一化")
    return [item / norm for item in values]


def build_rows() -> list[dict[str, object]]:
    return [
        {
            "id": "doc-milvus-1",
            "text": "Milvus 使用 collection、schema 和 index 组织向量数据",
            "source": "milvus-guide",
            "chunk_no": 1,
            "vector": l2_normalize([0.05, 0.08, 0.91, 0.13, 0.08, 0.04, 0.02, 0.0]),
        },
        {
            "id": "doc-python-1",
            "text": "Python 的上下文管理器用于可靠释放资源",
            "source": "python-guide",
            "chunk_no": 1,
            "vector": l2_normalize([0.92, 0.11, 0.08, 0.03, 0.02, 0.01, 0.0, 0.0]),
        },
    ]


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


def main() -> None:
    client = connect_client()
    try:
        recreate_collection(client)
        insert_result = client.upsert(collection_name=COLLECTION_NAME, data=build_rows())
        results = client.search(
            collection_name=COLLECTION_NAME,
            data=[l2_normalize([0.05, 0.08, 0.90, 0.14, 0.08, 0.04, 0.02, 0.0])],
            limit=2,
            output_fields=["text", "source", "chunk_no"],
            search_params={"metric_type": "COSINE"},
        )
        top_hit = results[0][0]
        print(f"uri={MILVUS_URI}")
        print(f"upsert_count={insert_result.get('upsert_count') or insert_result.get('insert_count')}")
        print(f"top_hit={top_hit['id']} score={top_hit['distance']:.4f}")
        print(f"top_text={top_hit['entity']['text']}")
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
