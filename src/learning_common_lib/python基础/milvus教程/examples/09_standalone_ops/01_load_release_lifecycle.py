"""
目标: 理解 Standalone 上 collection 必须 load 才能搜索的生命周期，Lite 会隐藏这一步
关键 API: load_collection, release_collection, get_load_state, refresh_load
本例重点参数:
- load_collection(collection_name): 把 collection 加载到 query node 内存，Standalone 检索前需要确认 load 状态。
- release_collection(collection_name): 释放查询内存，冷数据或下线集合可释放。
- get_load_state(collection_name): 排查搜索报 collection not loaded 时先看这个状态。
流程索引: roadmap.md#milvus-工程使用流程
Python 版本: 3.11+
运行命令: MILVUS_URI=http://localhost:19530 uv run python examples/09_standalone_ops/01_load_release_lifecycle.py
环境准备: 必须连接真实 Milvus Standalone（localhost:19530）；Milvus Lite 不区分 load/release，本示例无意义
预期现象: release 后搜索报 collection not loaded，load 后恢复；打印各阶段 load 状态
生产提醒: load 把数据从对象存储加载进 query node 内存；冷数据 release 释放内存，热数据保持 load
"""

import math
import os
import logging

from pymilvus import DataType, MilvusClient
from pymilvus.exceptions import MilvusException


# 本示例会故意触发一次 "collection not loaded"，提高 pymilvus 日志级别避免打印预期内的 RPC 错误栈
logging.getLogger("pymilvus").setLevel(logging.CRITICAL)


# 本示例针对真实 Standalone；默认指向本机 19530
MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_load_release")
DIMENSION = int(os.getenv("MILVUS_DIMENSION", "8"))
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "20"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """本机 gRPC 连接必须绕过 HTTP 代理。"""
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise ValueError("零向量不能归一化")
    return [x / norm for x in vector]


def connect_client(uri: str, token: str, timeout: float) -> MilvusClient:
    kwargs: dict[str, object] = {"uri": uri, "timeout": timeout}
    if token:
        kwargs["token"] = token
    return MilvusClient(**kwargs)


def recreate_collection(client: MilvusClient, name: str, dimension: int) -> None:
    if client.has_collection(name):
        client.drop_collection(name)
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dimension)
    index_params = client.prepare_index_params()
    index_params.add_index(field_name="vector", index_type="IVF_FLAT", metric_type="COSINE", params={"nlist": 16})
    client.create_collection(collection_name=name, schema=schema, index_params=index_params)


def main() -> None:
    ensure_local_no_proxy()
    if MILVUS_URI.endswith(".db"):
        print("本示例演示的是 Standalone 的 load/release 生命周期，Milvus Lite 不适用")
        print("请用 MILVUS_URI=http://localhost:19530 运行")
        return

    client = connect_client(MILVUS_URI, MILVUS_TOKEN, TIMEOUT_SECONDS)
    try:
        recreate_collection(client, COLLECTION_NAME, DIMENSION)
        rows = [{"id": f"doc-{i}", "vector": l2_normalize([i % 5 + 0.1] * DIMENSION)} for i in range(20)]
        client.insert(collection_name=COLLECTION_NAME, data=rows)

        # 建好集合默认是 Loaded 状态
        print(f"建集合后 load_state={client.get_load_state(collection_name=COLLECTION_NAME)['state']}")

        query_vector = [l2_normalize([0.5] * DIMENSION)]
        search_params = {"metric_type": "COSINE"}

        # release：把数据从 query node 内存释放，省内存但不能再搜
        client.release_collection(collection_name=COLLECTION_NAME)
        print(f"release 后 load_state={client.get_load_state(collection_name=COLLECTION_NAME)['state']}")
        try:
            client.search(collection_name=COLLECTION_NAME, data=query_vector, limit=3, search_params=search_params)
        except MilvusException as exc:
            print(f"release 后搜索失败 code={exc.code} reason=collection not loaded")

        # load：重新加载进内存才能搜索
        client.load_collection(collection_name=COLLECTION_NAME)
        print(f"load 后 load_state={client.get_load_state(collection_name=COLLECTION_NAME)['state']}")
        hits = client.search(collection_name=COLLECTION_NAME, data=query_vector, limit=3, search_params=search_params)
        print(f"load 后搜索命中数={len(hits[0])}")
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
