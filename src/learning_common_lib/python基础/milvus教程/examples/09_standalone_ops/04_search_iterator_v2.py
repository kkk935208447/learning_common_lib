"""
目标: 在 Standalone 上用 search_iterator 流式遍历大结果集，V2 迭代器在真实服务端完整可用
关键 API: search_iterator, iterator.next, iterator.close, batch_size, limit
Python 版本: 3.11+
运行命令: MILVUS_URI=http://localhost:19530 uv run python examples/09_standalone_ops/04_search_iterator_v2.py
环境准备: 必须连接真实 Milvus Standalone（localhost:19530）；Lite 上 search_iterator 会回退到 V1
预期现象: 分批拉取检索结果，打印每批大小和累计数量，最后 close 迭代器
生产提醒: 大 topK 检索用 iterator 控制单批内存；迭代器是有状态资源，用完必须 close
"""

import math
import os
import random

from pymilvus import DataType, MilvusClient


MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_search_iterator")
DIMENSION = int(os.getenv("MILVUS_DIMENSION", "8"))
TOTAL_ROWS = int(os.getenv("MILVUS_TOTAL_ROWS", "200"))
BATCH_SIZE = int(os.getenv("MILVUS_BATCH_SIZE", "50"))
LIMIT = int(os.getenv("MILVUS_LIMIT", "120"))
TIMEOUT_SECONDS = float(os.getenv("MILVUS_TIMEOUT", "30"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
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


def recreate_collection(client: MilvusClient, name: str, dimension: int, total_rows: int) -> None:
    if client.has_collection(name):
        client.drop_collection(name)
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dimension)
    index_params = client.prepare_index_params()
    index_params.add_index(field_name="vector", index_type="IVF_FLAT", metric_type="COSINE", params={"nlist": 32})
    client.create_collection(collection_name=name, schema=schema, index_params=index_params)
    # 用分散的随机向量，保证检索能召回足够多的结果供迭代器分批
    rng = random.Random(42)
    rows = [
        {"id": f"doc-{i}", "vector": l2_normalize([rng.random() for _ in range(dimension)])}
        for i in range(total_rows)
    ]
    client.insert(collection_name=name, data=rows)
    client.flush(collection_name=name)


def main() -> None:
    ensure_local_no_proxy()
    if MILVUS_URI.endswith(".db"):
        print("Lite 上 search_iterator 会回退到 V1，本示例演示 Standalone 的完整迭代器")
        print("请用 MILVUS_URI=http://localhost:19530 运行")
        return

    client = connect_client(MILVUS_URI, MILVUS_TOKEN, TIMEOUT_SECONDS)
    try:
        recreate_collection(client, COLLECTION_NAME, DIMENSION, TOTAL_ROWS)

        iterator = client.search_iterator(
            collection_name=COLLECTION_NAME,
            data=[l2_normalize([0.5] * DIMENSION)],
            batch_size=BATCH_SIZE,
            limit=LIMIT,
            anns_field="vector",
            search_params={"metric_type": "COSINE", "params": {"nprobe": 32}},
        )
        total = 0
        batch_no = 0
        try:
            while True:
                batch = iterator.next()
                if not batch:
                    break
                batch_no += 1
                total += len(batch)
                print(f"第 {batch_no} 批 batch_size={len(batch)} 累计={total}")
        finally:
            # 迭代器是有状态资源，必须关闭
            iterator.close()

        print(f"search_iterator 共拉取 {total} 条（limit={LIMIT}），分 {batch_no} 批")
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
