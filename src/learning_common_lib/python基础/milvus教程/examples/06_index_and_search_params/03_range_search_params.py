"""
目标: 使用 Milvus Lite 对比普通 topK 搜索和 range search 参数
关键 API: search_params, metric_type, radius, range_filter, limit
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/06_index_and_search_params/03_range_search_params.py
环境准备: 默认使用 Milvus Lite DB；也可设置 MILVUS_URI=http://localhost:19530 连接 Standalone
预期现象: 普通 topK 返回 3 条，range search 只返回满足距离阈值的候选
生产提醒: radius/range_filter 的含义受 metric_type 影响，必须用业务评测集校准
"""

from __future__ import annotations

import os
from pathlib import Path

from pymilvus import DataType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "4"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/range_search_params.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_range_search_params")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """Milvus Lite 本机 gRPC 端口不应走代理。"""
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


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
    schema.add_field("label", DataType.VARCHAR, max_length=64)

    index_params = client.prepare_index_params()
    index_params.add_index("vector", index_type="AUTOINDEX", metric_type="L2")
    client.create_collection(COLLECTION_NAME, schema=schema, index_params=index_params, consistency_level="Strong")
    client.insert(
        COLLECTION_NAME,
        [
            {"id": "near", "label": "近邻", "vector": [0.0, 0.0, 0.0, 0.0]},
            {"id": "middle", "label": "中等距离", "vector": [0.4, 0.0, 0.0, 0.0]},
            {"id": "far", "label": "远距离", "vector": [0.9, 0.0, 0.0, 0.0]},
        ],
    )


def main() -> None:
    client = connect_client()
    try:
        recreate_collection(client)
        query_vector = [[0.0, 0.0, 0.0, 0.0]]
        topk_results = client.search(
            collection_name=COLLECTION_NAME,
            data=query_vector,
            limit=3,
            output_fields=["label"],
            search_params={"metric_type": "L2", "params": {}},
        )
        range_results = client.search(
            collection_name=COLLECTION_NAME,
            data=query_vector,
            limit=3,
            output_fields=["label"],
            search_params={"metric_type": "L2", "params": {"radius": 0.5, "range_filter": 0.0}},
        )

        print(f"topk_ids={[hit['id'] for hit in topk_results[0]]}")
        print(f"topk_distances={[round(float(hit['distance']), 4) for hit in topk_results[0]]}")
        print(f"range_ids={[hit['id'] for hit in range_results[0]]}")
        print(f"range_count={len(range_results[0])}")
        print("L2 下距离越小越相似；这里 radius/range_filter 只保留距离在指定范围内的结果。")
        assert len(topk_results[0]) == 3
        assert len(range_results[0]) < len(topk_results[0])
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
