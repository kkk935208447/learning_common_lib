"""
目标: 使用 Milvus Lite 真实演示多向量字段 hybrid_search
关键 API: AnnSearchRequest, WeightedRanker, RRFRanker, hybrid_search
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/08_hybrid_search/01_hybrid_request.py
环境准备: 默认使用 Milvus Lite DB；也可设置 MILVUS_URI=http://localhost:19530 连接 Standalone
预期现象: dense_vector 和 title_vector 两路召回，经 WeightedRanker 融合后返回统一 top hit
生产提醒: hybrid search 的每个向量字段都需要 schema 字段、索引和对应 AnnSearchRequest
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable
from pathlib import Path

from pymilvus import AnnSearchRequest, DataType, MilvusClient, RRFRanker, WeightedRanker


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "4"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/hybrid_request.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_hybrid_request")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """Milvus Lite 本机 gRPC 连接必须绕过 HTTP 代理。"""
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
    schema.add_field("dense_vector", DataType.FLOAT_VECTOR, dim=DIMENSION)
    schema.add_field("title_vector", DataType.FLOAT_VECTOR, dim=DIMENSION)
    schema.add_field("title", DataType.VARCHAR, max_length=256)
    schema.add_field("category", DataType.VARCHAR, max_length=64)

    index_params = client.prepare_index_params()
    index_params.add_index("dense_vector", index_type="AUTOINDEX", metric_type="COSINE")
    index_params.add_index("title_vector", index_type="AUTOINDEX", metric_type="COSINE")

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
                "id": "doc-hybrid-milvus",
                "title": "Milvus hybrid search",
                "category": "milvus",
                "dense_vector": l2_normalize([0.90, 0.10, 0.05, 0.02]),
                "title_vector": l2_normalize([0.88, 0.12, 0.06, 0.02]),
            },
            {
                "id": "doc-partition-alias",
                "title": "Milvus partition alias",
                "category": "milvus",
                "dense_vector": l2_normalize([0.76, 0.34, 0.08, 0.04]),
                "title_vector": l2_normalize([0.80, 0.30, 0.10, 0.04]),
            },
            {
                "id": "doc-python-async",
                "title": "Python async client lifecycle",
                "category": "python",
                "dense_vector": l2_normalize([0.05, 0.88, 0.12, 0.04]),
                "title_vector": l2_normalize([0.04, 0.91, 0.10, 0.03]),
            },
        ],
    )


def run_hybrid_search(client: MilvusClient) -> None:
    dense_request = AnnSearchRequest(
        data=[l2_normalize([0.89, 0.11, 0.05, 0.02])],
        anns_field="dense_vector",
        param={"metric_type": "COSINE"},
        limit=3,
        expr='category == "milvus"',
    )
    title_request = AnnSearchRequest(
        data=[l2_normalize([0.87, 0.13, 0.06, 0.02])],
        anns_field="title_vector",
        param={"metric_type": "COSINE"},
        limit=3,
        expr='category == "milvus"',
    )

    weighted_results = client.hybrid_search(
        collection_name=COLLECTION_NAME,
        reqs=[dense_request, title_request],
        ranker=WeightedRanker(0.7, 0.3),
        limit=2,
        output_fields=["title", "category"],
    )
    rrf_results = client.hybrid_search(
        collection_name=COLLECTION_NAME,
        reqs=[dense_request, title_request],
        ranker=RRFRanker(),
        limit=2,
        output_fields=["title", "category"],
    )

    print(f"dense_request_field={dense_request.anns_field}")
    print(f"title_request_field={title_request.anns_field}")
    print(f"weighted_top_hit={weighted_results[0][0]['id']}")
    print(f"weighted_top_entity={weighted_results[0][0]['entity']}")
    print(f"rrf_top_hit={rrf_results[0][0]['id']}")
    assert weighted_results[0][0]["id"] == "doc-hybrid-milvus"


def main() -> None:
    client = connect_client()
    try:
        recreate_collection(client)
        run_hybrid_search(client)
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
