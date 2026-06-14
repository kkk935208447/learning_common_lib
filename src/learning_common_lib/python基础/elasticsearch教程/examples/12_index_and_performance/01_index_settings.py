"""
目标: 理解 shard/replica/refresh_interval 等核心索引设置，及批量导入时的调优手法
关键 API: indices.create(settings), indices.put_settings, number_of_shards/replicas, refresh_interval
Python 版本: 3.11+
运行命令: uv run python examples/12_index_and_performance/01_index_settings.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200（单节点）
预期现象: 打印索引设置；演示导入时关闭 refresh、导入后恢复并 force merge 的调优套路
生产提醒: shard 数创建后不可改；refresh_interval=-1 提升写入吞吐但牺牲可见性，导入完必须恢复
"""

import os

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_index_settings")
# 单节点环境副本设 0，否则副本无处分配会让索引一直 yellow
NUMBER_OF_SHARDS = int(os.getenv("ES_SHARDS", "1"))
NUMBER_OF_REPLICAS = int(os.getenv("ES_REPLICAS", "0"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def create_index(client: Elasticsearch, index_name: str, shards: int, replicas: int) -> None:
    client.options(ignore_status=404).indices.delete(index=index_name)
    client.indices.create(
        index=index_name,
        settings={
            "number_of_shards": shards,
            "number_of_replicas": replicas,
            "refresh_interval": "1s",
        },
        mappings={"properties": {"seq": {"type": "integer"}, "text": {"type": "text"}}},
    )


def gen_actions(index_name: str, count: int):
    for i in range(count):
        yield {"_index": index_name, "_id": str(i), "_source": {"seq": i, "text": f"文档内容 {i}"}}


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=30)
    try:
        create_index(client, INDEX_NAME, NUMBER_OF_SHARDS, NUMBER_OF_REPLICAS)
        settings = client.indices.get_settings(index=INDEX_NAME)[INDEX_NAME]["settings"]["index"]
        print(f"shards={settings['number_of_shards']} replicas={settings['number_of_replicas']} refresh={settings.get('refresh_interval')}")

        # 批量导入调优套路：导入前关闭周期 refresh，减少 segment 生成开销
        client.indices.put_settings(index=INDEX_NAME, settings={"refresh_interval": "-1"})
        print("导入前 refresh_interval 已设为 -1（关闭周期刷新）")

        success, _ = helpers.bulk(client, gen_actions(INDEX_NAME, 500))
        print(f"批量导入完成 success={success}")

        # 导入后恢复 refresh，并手动刷新让数据可见
        client.indices.put_settings(index=INDEX_NAME, settings={"refresh_interval": "1s"})
        client.indices.refresh(index=INDEX_NAME)
        print("导入后已恢复 refresh_interval=1s 并手动刷新")

        # force merge 把小 segment 合并成更少的大 segment，提升后续查询性能（仅对只读索引推荐）
        client.indices.forcemerge(index=INDEX_NAME, max_num_segments=1)
        print(f"force merge 完成，文档总数={client.count(index=INDEX_NAME)['count']}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
