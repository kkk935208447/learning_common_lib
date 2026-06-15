"""
目标: 用 alias + reindex 实现零停机的 mapping 变更（蓝绿索引切换）
关键 API: indices.create, reindex, indices.update_aliases, indices.get_alias
本例重点参数:
- indices.update_aliases(actions): 在一个请求里 remove/add，保证 alias 切换原子性。
- reindex(source/dest/refresh): 把旧索引数据重建到新索引；大数据量可用 wait_for_completion=False 转长任务。
- indices.get_alias(name): 验证 alias 当前指向，是发布后排查的关键 API。
Python 版本: 3.11+
运行命令: uv run python examples/09_production/01_alias_reindex.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 应用始终查询 alias；底层从 v1 索引重建到 v2 索引并原子切换 alias，查询不中断
生产提醒: 永远让应用读写 alias 而非物理索引名；mapping 变更走新索引 + reindex + alias 原子切换
"""

import os

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
ALIAS = os.getenv("ES_ALIAS", "learning_es_articles")
INDEX_V1 = f"{ALIAS}_v1"
INDEX_V2 = f"{ALIAS}_v2"
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def cleanup(client: Elasticsearch) -> None:
    for index in (INDEX_V1, INDEX_V2):
        client.options(ignore_status=404).indices.delete(index=index)


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=30)
    try:
        cleanup(client)

        # v1：初始索引，title 是 text
        client.indices.create(index=INDEX_V1, mappings={"properties": {"title": {"type": "text"}}})
        # alias 指向 v1，应用只认 alias
        client.indices.update_aliases(actions=[{"add": {"index": INDEX_V1, "alias": ALIAS}}])

        actions = [
            {"_index": ALIAS, "_id": str(i), "_source": {"title": f"文章 {i}"}} for i in range(5)
        ]
        helpers.bulk(client, actions, refresh="wait_for")
        print(f"alias 当前指向={list(client.indices.get_alias(name=ALIAS).keys())}")
        print(f"通过 alias 查询命中={client.count(index=ALIAS)['count']}")

        # 需求变更：title 增加 keyword 子字段。新建 v2 用新 mapping
        client.indices.create(
            index=INDEX_V2,
            mappings={"properties": {"title": {"type": "text", "fields": {"raw": {"type": "keyword"}}}}},
        )
        # 把 v1 数据重建到 v2
        client.reindex(source={"index": INDEX_V1}, dest={"index": INDEX_V2}, refresh=True)

        # 原子切换：同一请求里移除旧映射、加入新映射，应用查询不中断
        client.indices.update_aliases(
            actions=[
                {"remove": {"index": INDEX_V1, "alias": ALIAS}},
                {"add": {"index": INDEX_V2, "alias": ALIAS}},
            ]
        )
        print(f"切换后 alias 指向={list(client.indices.get_alias(name=ALIAS).keys())}")
        print(f"切换后通过 alias 查询命中={client.count(index=ALIAS)['count']}")

        # 新 mapping 生效：可以用 title.raw 聚合
        agg = client.search(index=ALIAS, size=0, aggs={"titles": {"terms": {"field": "title.raw"}}})
        print(f"v2 新增 title.raw 聚合桶数={len(agg['aggregations']['titles']['buckets'])}")
    finally:
        client.options(ignore_status=404).indices.delete_alias(index="*", name=ALIAS)
        cleanup(client)
        client.close()


if __name__ == "__main__":
    main()
