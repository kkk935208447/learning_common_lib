"""
目标: 演示 Milvus 向量检索与 scalar filter、query、delete 的组合
关键 API: search(filter=...), query, delete
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/03_filter_and_crud/02_scalar_filter_query_delete.py
环境准备: 默认使用 Milvus Lite；也可设置 MILVUS_URI 和 MILVUS_TOKEN 连接 Standalone
预期现象: 打印过滤后的 top hit、query 数量、delete 数量
生产提醒: filter 字符串应由受控字段构造，不要直接拼接用户输入
"""

import math
import os
from pathlib import Path
from typing import Iterable

from pymilvus import DataType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "8"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/milvus_lite.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_filter_query_delete")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """Milvus Lite 的本机 gRPC 连接不应经过 HTTP 代理。"""
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
        raise ValueError("查询向量维度错误或为零向量")
    return [item / norm for item in values]


def build_rows() -> list[dict[str, object]]:
    vectors = {
        "doc-python-1": [0.92, 0.11, 0.08, 0.03, 0.02, 0.01, 0.0, 0.0],
        "doc-python-2": [0.84, 0.22, 0.14, 0.06, 0.03, 0.02, 0.0, 0.0],
        "doc-milvus-1": [0.05, 0.08, 0.91, 0.13, 0.08, 0.04, 0.02, 0.0],
        "doc-milvus-2": [0.04, 0.05, 0.88, 0.20, 0.10, 0.05, 0.03, 0.0],
    }
    return [
        {"id": "doc-python-1", "text": "Python 上下文管理器释放资源", "source": "python-guide", "chunk_no": 1, "vector": l2_normalize(vectors["doc-python-1"])},
        {"id": "doc-python-2", "text": "asyncio 适合处理 I/O 等待", "source": "python-guide", "chunk_no": 2, "vector": l2_normalize(vectors["doc-python-2"])},
        {"id": "doc-milvus-1", "text": "Milvus 使用 collection 和 index 组织向量", "source": "milvus-guide", "chunk_no": 1, "vector": l2_normalize(vectors["doc-milvus-1"])},
        {"id": "doc-milvus-2", "text": "向量检索可以结合 scalar filter", "source": "milvus-guide", "chunk_no": 2, "vector": l2_normalize(vectors["doc-milvus-2"])},
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


def delete_count(result: object) -> int:
    """兼容 Lite 和服务端不同版本的 delete 返回结构。"""
    if isinstance(result, dict):
        return int(result.get("delete_count") or 0)
    if isinstance(result, list):
        return len(result)
    return 0


def main() -> None:
    client = connect_client()
    try:
        recreate_collection(client)
        client.upsert(collection_name=COLLECTION_NAME, data=build_rows())
        results = client.search(
            collection_name=COLLECTION_NAME,
            data=[l2_normalize([0.05, 0.08, 0.90, 0.14, 0.08, 0.04, 0.02, 0.0])],
            limit=3,
            filter='source == "milvus-guide"',
            output_fields=["text", "source", "chunk_no"],
            search_params={"metric_type": "COSINE"},
        )
        rows = client.query(COLLECTION_NAME, filter='source == "milvus-guide"', output_fields=["id", "text"], limit=100)
        delete_result = client.delete(COLLECTION_NAME, filter='source == "python-guide"')
        remaining = client.query(COLLECTION_NAME, filter='source == "python-guide"', output_fields=["id"], limit=100)

        print(f"filtered_top_hit={results[0][0]['id']}")
        print(f"milvus_rows={len(rows)}")
        print(f"deleted_python_rows={delete_count(delete_result)}")
        print(f"remaining_python_rows={len(remaining)}")
        assert len(remaining) == 0
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
