"""
目标: 使用 Milvus Lite 创建包含多个向量字段的 collection，并验证每个字段的索引参数
关键 API: create_schema, prepare_index_params, add_index, create_collection, describe_collection, list_indexes, describe_index
本例重点参数:
- add_field(enable_analyzer=True): 文本字段启用 analyzer 后，才能作为 BM25 Function 的输入。
- add_index(field_name, index_name, index_type, metric_type, params): 多向量字段要分别建索引，dense/title/sparse 的度量不能混用。
- describe_index(collection_name, index_name): 观察服务端实际索引类型、度量方式、索引状态和行数。
流程索引: roadmap.md#milvus-工程使用流程
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/06_index_and_search_params/02_build_multiple_index_params.py
环境准备: 默认使用 Milvus Lite DB；也可设置 MILVUS_URI=http://localhost:19530 连接 Standalone
预期现象: dense_vector、title_vector、sparse_vector 三个字段都有对应索引配置
生产提醒: 多向量字段常用于正文向量、标题向量、BM25 稀疏向量的混合检索
"""

from __future__ import annotations

import os
from pathlib import Path

from pymilvus import DataType, Function, FunctionType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "4"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/multiple_index_params.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_multiple_index_params")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """Milvus Lite 的本机 gRPC 连接需要绕过 HTTP 代理。"""
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


def build_schema_and_indexes(client: MilvusClient) -> tuple[object, object]:
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
    schema.add_field("text", DataType.VARCHAR, max_length=1024, enable_analyzer=True)
    schema.add_field("dense_vector", DataType.FLOAT_VECTOR, dim=DIMENSION)
    schema.add_field("title_vector", DataType.FLOAT_VECTOR, dim=DIMENSION)
    schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_function(
        Function(
            name="text_bm25",
            input_field_names=["text"],
            output_field_names=["sparse_vector"],
            function_type=FunctionType.BM25,
        )
    )

    index_params = client.prepare_index_params()
    index_params.add_index("dense_vector", index_name="dense_auto", index_type="AUTOINDEX", metric_type="COSINE")
    index_params.add_index("title_vector", index_name="title_auto", index_type="AUTOINDEX", metric_type="COSINE")
    index_params.add_index(
        "sparse_vector",
        index_name="sparse_bm25",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
        params={"inverted_index_algo": "DAAT_MAXSCORE"},
    )
    return schema, index_params


def main() -> None:
    client = connect_client()
    try:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)

        schema, index_params = build_schema_and_indexes(client)
        client.create_collection(
            collection_name=COLLECTION_NAME,
            schema=schema,
            index_params=index_params,
            consistency_level="Strong",
        )
        description = client.describe_collection(COLLECTION_NAME)
        field_names = [field["name"] for field in description["fields"]]
        index_names = client.list_indexes(collection_name=COLLECTION_NAME)

        print(f"fields={field_names}")
        for item in index_params:
            config = item.to_dict()
            print(
                "index_config="
                f"field={config['field_name']} "
                f"name={config.get('index_name')} "
                f"type={config['index_type']} "
                f"metric={config['metric_type']} "
                f"params={config.get('params', {})}"
            )
        print(f"list_indexes={index_names}")
        for index_name in index_names:
            detail = client.describe_index(collection_name=COLLECTION_NAME, index_name=index_name)
            print(
                "describe_index="
                f"field={detail['field_name']} "
                f"name={detail['index_name']} "
                f"type={detail['index_type']} "
                f"metric={detail['metric_type']} "
                f"state={detail.get('state')}"
            )

        assert {"dense_vector", "title_vector", "sparse_vector"}.issubset(field_names)
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
