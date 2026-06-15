"""
目标: 理解 Standalone 的 segment 管理：flush 落盘、compact 合并、stats 查看实体数
关键 API: flush, compact, get_collection_stats
本例重点参数:
- flush(collection_name): 强制 growing segment 封口落盘，不能每写一条就调用。
- compact(collection_name, is_clustering, is_l0, target_size, target_size_unit): 后台合并 segment、回收删除空间，是低峰运维操作。
- get_collection_stats(collection_name): 查看 row_count 等统计信息，键集合受版本和部署模式影响。
流程索引: roadmap.md#milvus-工程使用流程
Python 版本: 3.11+
运行命令: MILVUS_URI=http://localhost:19530 uv run python examples/09_standalone_ops/02_flush_compact_stats.py
环境准备: 必须连接真实 Milvus Standalone（localhost:19530）；Lite 没有独立的 segment/对象存储层
预期现象: flush 后实体落盘成 sealed segment，删除后 compact 回收空间，stats 反映实体数
生产提醒: flush 强制生成 segment 有成本，别每写一条就 flush；compact 是后台重操作，低峰触发
"""

import math
import os

from pymilvus import DataType, MilvusClient


MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "learning_milvus_flush_compact")
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
        print("flush/compact/segment 是 Standalone 的服务端概念，Lite 不适用")
        print("请用 MILVUS_URI=http://localhost:19530 运行")
        return

    client = connect_client(MILVUS_URI, MILVUS_TOKEN, TIMEOUT_SECONDS)
    try:
        recreate_collection(client, COLLECTION_NAME, DIMENSION)
        rows = [{"id": f"doc-{i}", "vector": l2_normalize([i % 7 + 0.1] * DIMENSION)} for i in range(100)]
        client.insert(collection_name=COLLECTION_NAME, data=rows)

        # flush：把内存里的 growing segment 强制封口成 sealed segment 落盘
        client.flush(collection_name=COLLECTION_NAME)
        stats = client.get_collection_stats(collection_name=COLLECTION_NAME)
        print(f"flush 后实体数 row_count={stats['row_count']}")

        # 删除一半数据，再 compact 触发后台合并回收被删实体占用的空间
        delete_ids = [f"doc-{i}" for i in range(50)]
        client.delete(collection_name=COLLECTION_NAME, ids=delete_ids)
        client.flush(collection_name=COLLECTION_NAME)
        # compact 返回一个 job id（-1 表示无需 compaction 或立即完成）
        job_id = client.compact(collection_name=COLLECTION_NAME)
        print(f"删除 50 条后 compact job_id={job_id}")

        remaining = client.get_collection_stats(collection_name=COLLECTION_NAME)["row_count"]
        print(f"compact 后实体数 row_count={remaining}（删除会异步生效，可能仍含未回收实体）")
        # query 看真实可见数据，比 stats 更直接
        live = client.query(collection_name=COLLECTION_NAME, filter="", output_fields=["count(*)"])
        print(f"query count(*) 可见实体数={live[0]['count(*)']}")
    finally:
        if client.has_collection(COLLECTION_NAME):
            client.drop_collection(COLLECTION_NAME)
        client.close()


if __name__ == "__main__":
    main()
