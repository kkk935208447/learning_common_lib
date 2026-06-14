"""
目标: 演示重复写入同一批文档时使用 upsert 保持幂等
关键 API: upsert, query
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/04_errors_and_recovery/02_idempotent_upsert.py
环境准备: 默认使用 Milvus Lite；也可设置 MILVUS_URI 和 MILVUS_TOKEN 连接 Standalone
预期现象: 同一批数据 upsert 两次后，按 source 查询仍只有 2 条 Milvus 文档块
生产提醒: 批量导入任务应使用稳定主键，避免失败重跑时产生重复向量
"""

import math
import os
from pathlib import Path
from typing import Iterable

from pymilvus import DataType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "8"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/milvus_lite.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_idempotent_upsert")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """避免 Milvus Lite 的 127.0.0.1 gRPC 连接被代理拦截。"""
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
        {"id": "doc-milvus-1", "text": "Milvus collection schema index", "source": "milvus-guide", "chunk_no": 1, "vector": l2_normalize([0.05, 0.08, 0.91, 0.13, 0.08, 0.04, 0.02, 0.0])},
        {"id": "doc-milvus-2", "text": "Milvus scalar filter search", "source": "milvus-guide", "chunk_no": 2, "vector": l2_normalize([0.04, 0.05, 0.88, 0.20, 0.10, 0.05, 0.03, 0.0])},
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
    client.create_collection(COLLECTION_NAME, schema=schema, index_params=index_params, consistency_level="Strong")


def main() -> None:
    client = connect_client()
    try:
        recreate_collection(client)
        rows_to_write = build_rows()
        first_result = client.upsert(collection_name=COLLECTION_NAME, data=rows_to_write)
        # 中间状态：第一次写入后行数，应等于第二次写入后行数，证明 upsert 幂等
        rows_after_first = client.query(COLLECTION_NAME, filter='source == "milvus-guide"', output_fields=["id"], limit=100)
        second_result = client.upsert(collection_name=COLLECTION_NAME, data=rows_to_write)
        rows = client.query(COLLECTION_NAME, filter='source == "milvus-guide"', output_fields=["id"], limit=100)

        print(f"first_upsert_count={first_result.get('upsert_count') or first_result.get('insert_count')}")
        print(f"milvus_rows_after_first_run={len(rows_after_first)}")
        print(f"second_upsert_count={second_result.get('upsert_count') or second_result.get('insert_count')}")
        print(f"milvus_rows_after_two_runs={len(rows)}（与第一次相同说明没有重复写入）")
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
