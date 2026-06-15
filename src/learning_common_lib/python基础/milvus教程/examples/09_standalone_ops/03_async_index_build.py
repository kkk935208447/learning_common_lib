"""
目标: 用 AsyncMilvusClient 在 Standalone 上异步建集合、建索引、写入、加载、检索全链路
关键 API: AsyncMilvusClient, async create_collection, create_index, load_collection, search
本例重点参数:
- AsyncMilvusClient(uri, token, timeout): Standalone 上适合并发 DDL/检索，但 Lite 对部分异步 DDL RPC 支持有限。
- create_collection/create_index: 异步建集合和补建索引适合服务端初始化流程，不建议放在在线请求路径。
- flush/load_collection/search: 写入后先 flush/load，再 search 验证可见性和加载状态。
流程索引: roadmap.md#milvus-工程使用流程
Python 版本: 3.11+
运行命令: MILVUS_URI=http://localhost:19530 uv run python examples/09_standalone_ops/03_async_index_build.py
环境准备: 必须连接真实 Milvus Standalone（localhost:19530）；Milvus Lite 不支持异步建索引路径
预期现象: 异步完成建集合到检索的完整链路，打印命中数
生产提醒: Lite 下异步建索引会触发未实现 RPC；真实 Standalone 才支持异步 DDL，适合服务端并发初始化
"""

import asyncio
import math
import os

from pymilvus import AsyncMilvusClient, DataType, MilvusClient


MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_async_index")
DIMENSION = int(os.getenv("MILVUS_DIMENSION", "8"))
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


async def build_and_search(uri: str, token: str, name: str, dimension: int, timeout: float) -> None:
    async_client = AsyncMilvusClient(uri=uri, token=token or None, timeout=timeout)
    # has_collection / drop 用同步客户端做前置清理更稳妥
    sync_client = MilvusClient(uri=uri, token=token or None, timeout=timeout)
    try:
        if sync_client.has_collection(name):
            sync_client.drop_collection(name)

        schema = async_client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dimension)
        index_params = async_client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="IVF_FLAT", metric_type="COSINE", params={"nlist": 16})

        # 异步建集合并建索引：这条路径在 Milvus Lite 会触发未实现 RPC
        await async_client.create_collection(collection_name=name, schema=schema, index_params=index_params)

        rows = [{"id": f"doc-{i}", "vector": l2_normalize([i % 5 + 0.1] * dimension)} for i in range(30)]
        await async_client.insert(collection_name=name, data=rows)

        # 先 flush 让数据落盘成 sealed segment，再 load 才能搜到刚写入的数据
        await async_client.flush(collection_name=name)
        await async_client.load_collection(collection_name=name)

        results = await async_client.search(
            collection_name=name,
            data=[l2_normalize([0.5] * dimension)],
            limit=3,
            anns_field="vector",
            search_params={"metric_type": "COSINE", "params": {"nprobe": 16}},
        )
        print(f"异步建索引并检索成功，命中数={len(results[0])}")
    finally:
        if sync_client.has_collection(name):
            sync_client.drop_collection(name)
        await async_client.close()
        sync_client.close()


def main() -> None:
    ensure_local_no_proxy()
    if MILVUS_URI.endswith(".db"):
        print("Milvus Lite 不支持异步建索引路径，本示例需要 Standalone")
        print("请用 MILVUS_URI=http://localhost:19530 运行")
        return
    asyncio.run(build_and_search(MILVUS_URI, MILVUS_TOKEN, COLLECTION_NAME, DIMENSION, TIMEOUT_SECONDS))


if __name__ == "__main__":
    main()
