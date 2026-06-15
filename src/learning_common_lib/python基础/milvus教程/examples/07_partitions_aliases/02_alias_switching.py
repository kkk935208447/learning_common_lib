"""
目标: 使用 Milvus Lite 真实演示 alias 蓝绿切换和回滚
关键 API: create_alias, alter_alias, list_aliases, describe_alias, drop_alias, search
本例重点参数:
- create_alias(collection_name, alias): 创建稳定逻辑名，在线服务应查 alias 而不是物理 collection。
- alter_alias(collection_name, alias): 原子切换 alias 指向，用于蓝绿发布和回滚。
- describe_alias(alias): 发布前后确认当前指向，避免服务仍读旧 collection。
流程索引: roadmap.md#milvus-工程使用流程
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/07_partitions_aliases/02_alias_switching.py
环境准备: 默认使用 Milvus Lite DB；也可设置 MILVUS_URI=http://localhost:19530 连接 Standalone
预期现象: alias 先指向 v1，切到 v2 后搜索结果变化，再回滚到 v1
生产提醒: 在线服务查询稳定 alias；新版本 collection 验证通过后再 alter_alias
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable
from pathlib import Path

from pymilvus import DataType, MilvusClient


DIMENSION = int(os.getenv("MILVUS_DIMENSION", "8"))
MILVUS_URI = os.getenv("MILVUS_URI", ".milvus_tutorial/alias_switching.db")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_V1 = os.getenv("MILVUS_COLLECTION_V1", "learning_milvus_alias_docs_v1")
COLLECTION_V2 = os.getenv("MILVUS_COLLECTION_V2", "learning_milvus_alias_docs_v2")
ALIAS_NAME = os.getenv("MILVUS_ALIAS_NAME", "learning_milvus_alias_current")
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """避免 Milvus Lite 的本机 gRPC 连接被 HTTP 代理接管。"""
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


def create_version_collection(client: MilvusClient, collection_name: str, *, version_label: str) -> None:
    if client.has_collection(collection_name):
        client.drop_collection(collection_name)

    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=DIMENSION)
    schema.add_field("text", DataType.VARCHAR, max_length=1024)
    schema.add_field("version", DataType.VARCHAR, max_length=32)

    index_params = client.prepare_index_params()
    index_params.add_index("vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params,
        consistency_level="Strong",
    )
    client.insert(
        collection_name,
        [
            {
                "id": f"{version_label}-milvus",
                "text": f"{version_label} Milvus alias 发布说明",
                "version": version_label,
                "vector": l2_normalize([0.05, 0.08, 0.91, 0.13, 0.08, 0.04, 0.02, 0.0]),
            },
            {
                "id": f"{version_label}-python",
                "text": f"{version_label} Python 生命周期说明",
                "version": version_label,
                "vector": l2_normalize([0.90, 0.12, 0.08, 0.04, 0.02, 0.01, 0.0, 0.0]),
            },
        ],
    )


def search_service_alias(client: MilvusClient) -> dict[str, object]:
    result = client.search(
        collection_name=ALIAS_NAME,
        data=[l2_normalize([0.05, 0.08, 0.90, 0.14, 0.08, 0.04, 0.02, 0.0])],
        limit=1,
        output_fields=["text", "version"],
        search_params={"metric_type": "COSINE"},
    )
    hit = result[0][0]
    return {
        "id": hit["id"],
        "version": hit["entity"]["version"],
        "text": hit["entity"]["text"],
        "distance": round(float(hit["distance"]), 4),
    }


def safe_drop_alias(client: MilvusClient) -> None:
    for collection_name in (COLLECTION_V1, COLLECTION_V2):
        if client.has_collection(collection_name):
            aliases = client.list_aliases(collection_name=collection_name).get("aliases", [])
            if ALIAS_NAME in aliases:
                client.drop_alias(alias=ALIAS_NAME)
                return


def main() -> None:
    client = connect_client()
    try:
        safe_drop_alias(client)
        create_version_collection(client, COLLECTION_V1, version_label="v1")
        create_version_collection(client, COLLECTION_V2, version_label="v2")

        client.create_alias(collection_name=COLLECTION_V1, alias=ALIAS_NAME)
        before = search_service_alias(client)
        print(f"alias_created={client.list_aliases(collection_name=COLLECTION_V1)}")
        print(f"alias_target_before_switch={client.describe_alias(alias=ALIAS_NAME)}")
        print(f"service_search_before_switch={before}")
        assert before["version"] == "v1"

        v2_rows = client.query(COLLECTION_V2, filter='version == "v2"', output_fields=["id"], limit=10)
        print(f"v2_validation_row_count={len(v2_rows)}")
        assert len(v2_rows) == 2

        client.alter_alias(collection_name=COLLECTION_V2, alias=ALIAS_NAME)
        after_switch = search_service_alias(client)
        print(f"alias_after_switch={client.list_aliases(collection_name=COLLECTION_V2)}")
        print(f"alias_target_after_switch={client.describe_alias(alias=ALIAS_NAME)}")
        print(f"service_search_after_switch={after_switch}")
        assert after_switch["version"] == "v2"

        client.alter_alias(collection_name=COLLECTION_V1, alias=ALIAS_NAME)
        after_rollback = search_service_alias(client)
        print(f"alias_target_after_rollback={client.describe_alias(alias=ALIAS_NAME)}")
        print(f"service_search_after_rollback={after_rollback}")
        assert after_rollback["version"] == "v1"
    finally:
        safe_drop_alias(client)
        for collection in (COLLECTION_V1, COLLECTION_V2):
            if client.has_collection(collection):
                client.drop_collection(collection)
        client.close()


if __name__ == "__main__":
    main()
