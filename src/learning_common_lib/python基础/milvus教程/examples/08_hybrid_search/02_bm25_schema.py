"""
目标: 使用 Milvus Lite 真实演示 BM25 schema、Function、稀疏索引和关键词检索
关键 API: DataType.SPARSE_FLOAT_VECTOR, Function, FunctionType.BM25, enable_analyzer, search
本例重点参数:
- add_field(enable_analyzer=True): 文本字段启用 analyzer 后才能作为 BM25 输入。
- Function(input_field_names, output_field_names, function_type=FunctionType.BM25): 在 schema 期把文本映射到稀疏向量字段。
- SPARSE_INVERTED_INDEX(metric_type="BM25"): BM25 稀疏字段需要单独索引，不能临时在 search 中开启。
流程索引: roadmap.md#milvus-工程使用流程
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/08_hybrid_search/02_bm25_schema.py
环境准备: 默认使用 Milvus Lite DB；也可设置 MILVUS_URI=http://localhost:19530 连接 Standalone
预期现象: 查询 "milvus hybrid" 时，BM25 sparse_vector 命中 Milvus 混合检索文档
生产提醒: BM25 不是查询时临时参数，必须在 collection 创建期声明 analyzer、Function 和 sparse index
"""

from __future__ import annotations

import os
from pathlib import Path

from pymilvus import DataType, Function, FunctionType, MilvusClient


MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/bm25_schema.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_bm25_schema")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """BM25 示例也走 Lite 本机 gRPC，必须绕过代理。"""
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


def recreate_collection(client: MilvusClient) -> Function:
    if client.has_collection(COLLECTION_NAME):
        client.drop_collection(COLLECTION_NAME)

    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
    schema.add_field("text", DataType.VARCHAR, max_length=2048, enable_analyzer=True)
    schema.add_field("source", DataType.VARCHAR, max_length=128)
    schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)

    bm25_function = Function(
        name="text_bm25",
        input_field_names=["text"],
        output_field_names=["sparse_vector"],
        function_type=FunctionType.BM25,
    )
    schema.add_function(bm25_function)

    index_params = client.prepare_index_params()
    index_params.add_index(
        "sparse_vector",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
        params={"inverted_index_algo": "DAAT_MAXSCORE"},
    )

    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
        consistency_level="Strong",
    )
    return bm25_function


def insert_documents(client: MilvusClient) -> None:
    client.insert(
        COLLECTION_NAME,
        [
            {
                "id": "doc-milvus-hybrid",
                "text": "Milvus hybrid search combines dense vectors and BM25 sparse vectors.",
                "source": "milvus-guide",
            },
            {
                "id": "doc-python-async",
                "text": "Python async clients should be managed by service lifespan hooks.",
                "source": "python-guide",
            },
            {
                "id": "doc-alias-release",
                "text": "Milvus alias switching helps blue green collection releases.",
                "source": "milvus-guide",
            },
        ],
    )


def main() -> None:
    client = connect_client()
    try:
        bm25_function = recreate_collection(client)
        insert_documents(client)

        results = client.search(
            collection_name=COLLECTION_NAME,
            data=["milvus hybrid"],
            anns_field="sparse_vector",
            limit=3,
            output_fields=["text", "source"],
            search_params={"metric_type": "BM25"},
        )
        top_hit = results[0][0]

        print(f"function_name={bm25_function.name}")
        print(f"function_input={bm25_function.input_field_names}")
        print(f"function_output={bm25_function.output_field_names}")
        print(f"bm25_top_hit={top_hit['id']}")
        print(f"bm25_top_text={top_hit['entity']['text']}")
        print(f"bm25_score={top_hit['distance']:.4f}")
        assert top_hit["id"] == "doc-milvus-hybrid"
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
