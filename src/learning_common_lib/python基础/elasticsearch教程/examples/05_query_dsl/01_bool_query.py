"""
目标: 掌握 bool 查询的 must/filter/should/must_not 四个子句和它们对评分的影响
关键 API: search(query=bool), match, term, range, minimum_should_match
本例重点参数:
- bool.must/filter/should/must_not: must 参与评分，filter 不算分且可缓存，must_not 排除结果。
- minimum_should_match: 控制 should 至少命中几个条件，避免“可选条件”变成无效约束。
- search(size/sort): size 控制返回数量，sort 会改变默认按相关性排序的行为。
Python 版本: 3.11+
运行命令: uv run python examples/05_query_dsl/01_bool_query.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 打印不同子句组合的命中数，演示 filter 不算分、should 影响排序
生产提醒: 精确过滤放 filter（可缓存、不算分），相关性匹配放 must，能显著提升性能
"""

import os

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_bool_query")
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def seed(client: Elasticsearch, index_name: str) -> None:
    """重建索引并写入教学数据，保证示例自包含。"""
    client.options(ignore_status=404).indices.delete(index=index_name)
    client.indices.create(
        index=index_name,
        mappings={
            "properties": {
                "title": {"type": "text"},
                "tag": {"type": "keyword"},
                "price": {"type": "integer"},
            }
        },
    )
    docs = [
        {"title": "Elasticsearch 权威指南", "tag": "search", "price": 80},
        {"title": "Elasticsearch 性能调优", "tag": "search", "price": 120},
        {"title": "Python 并发编程", "tag": "python", "price": 60},
        {"title": "分布式搜索系统设计", "tag": "search", "price": 200},
    ]
    actions = [{"_index": index_name, "_id": str(i), "_source": d} for i, d in enumerate(docs)]
    helpers.bulk(client, actions, refresh="wait_for")


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        seed(client, INDEX_NAME)

        # must：参与算分的匹配条件
        must_only = client.search(index=INDEX_NAME, query={"bool": {"must": [{"match": {"title": "elasticsearch"}}]}})
        print(f"must match 'elasticsearch' 命中={must_only['hits']['total']['value']}")

        # filter：精确过滤，不算分，可缓存。这里叠加 tag=search 和 price 区间
        filtered = client.search(
            index=INDEX_NAME,
            query={
                "bool": {
                    "must": [{"match": {"title": "elasticsearch"}}],
                    "filter": [
                        {"term": {"tag": "search"}},
                        {"range": {"price": {"gte": 100}}},
                    ],
                }
            },
        )
        print(f"must + filter(tag=search, price>=100) 命中={filtered['hits']['total']['value']}")
        for hit in filtered["hits"]["hits"]:
            print(f"  hit={hit['_source']['title']} price={hit['_source']['price']} score={hit['_score']:.4f}")

        # must_not：排除条件
        excluded = client.search(
            index=INDEX_NAME,
            query={"bool": {"must_not": [{"term": {"tag": "python"}}]}},
        )
        print(f"must_not(tag=python) 命中={excluded['hits']['total']['value']}")

        # should + minimum_should_match：至少匹配 1 个可选条件
        should = client.search(
            index=INDEX_NAME,
            query={
                "bool": {
                    "should": [{"match": {"title": "性能"}}, {"match": {"title": "分布式"}}],
                    "minimum_should_match": 1,
                }
            },
        )
        print(f"should(性能 或 分布式) 命中={should['hits']['total']['value']}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
