"""
目标: 用 profile 剖析查询耗时定位慢查询，用 msearch 合并多个查询减少往返
关键 API: search(profile=True), msearch, request_cache
Python 版本: 3.11+
运行命令: uv run python examples/12_index_and_performance/03_profile_msearch.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 打印各查询类型的耗时分解，并用一次 msearch 拿到多个查询结果
生产提醒: profile 本身有开销，仅用于排查不要常开；msearch 适合首页多组聚合/查询一次取回
"""

import os

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_profile")
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def seed(client: Elasticsearch, index_name: str) -> None:
    client.options(ignore_status=404).indices.delete(index=index_name)
    client.indices.create(
        index=index_name,
        mappings={"properties": {"title": {"type": "text"}, "tag": {"type": "keyword"}}},
    )
    docs = [
        {"title": f"Elasticsearch 文档 {i}", "tag": "search" if i % 2 == 0 else "other"}
        for i in range(20)
    ]
    actions = [{"_index": index_name, "_id": str(i), "_source": d} for i, d in enumerate(docs)]
    helpers.bulk(client, actions, refresh="wait_for")


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        seed(client, INDEX_NAME)

        # profile=True：返回查询在各 shard 上的耗时分解，定位慢在哪个 query 节点
        profiled = client.search(
            index=INDEX_NAME,
            query={
                "bool": {
                    "must": [{"match": {"title": "elasticsearch"}}],
                    "filter": [{"term": {"tag": "search"}}],
                }
            },
            profile=True,
        )
        shard = profiled["profile"]["shards"][0]
        query_node = shard["searches"][0]["query"][0]
        print(f"profile 顶层查询类型={query_node['type']}")
        print(f"profile 耗时(纳秒)={query_node['time_in_nanos']}")
        print(f"命中数={profiled['hits']['total']['value']}")

        # msearch：把多个查询打包成一次请求，减少网络往返
        # 请求体是 [header, body, header, body, ...] 的交替结构
        searches = [
            {"index": INDEX_NAME},
            {"query": {"term": {"tag": "search"}}, "size": 0},
            {"index": INDEX_NAME},
            {"query": {"term": {"tag": "other"}}, "size": 0},
        ]
        multi = client.msearch(searches=searches)
        counts = [resp["hits"]["total"]["value"] for resp in multi["responses"]]
        print(f"msearch 一次取回两个查询命中数: tag=search -> {counts[0]}, tag=other -> {counts[1]}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
