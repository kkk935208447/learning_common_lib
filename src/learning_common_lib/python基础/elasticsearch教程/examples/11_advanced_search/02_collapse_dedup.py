"""
目标: 用 collapse 字段折叠按某字段去重，每组只返回 top 1，并保留组内更多命中
关键 API: search(collapse), inner_hits, field
本例重点参数:
- collapse.field: 必须是 keyword 或数值这类可排序/聚合字段，用于按业务键去重。
- inner_hits.name/size/sort: 取每组内更多文档，适合展示“同组其他结果”。
- search.limit/size: collapse 后 size 表示返回多少个分组代表，而不是原始文档数。
Python 版本: 3.11+
运行命令: uv run python examples/11_advanced_search/02_collapse_dedup.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 普通搜索返回同一作者的多条，collapse 后每个作者只保留评分最高的一条
生产提醒: collapse 用于“每个分组展示一条代表”，比聚合更适合直接拿文档；折叠字段必须是 keyword/数值
"""

import os

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_collapse")
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
        mappings={"properties": {"title": {"type": "text"}, "author": {"type": "keyword"}}},
    )
    docs = [
        {"title": "Elasticsearch 入门", "author": "alice"},
        {"title": "Elasticsearch 进阶", "author": "alice"},
        {"title": "Elasticsearch 调优", "author": "bob"},
        {"title": "Elasticsearch 运维", "author": "bob"},
        {"title": "Elasticsearch 安全", "author": "carol"},
    ]
    actions = [{"_index": index_name, "_id": str(i), "_source": d} for i, d in enumerate(docs)]
    helpers.bulk(client, actions, refresh="wait_for")


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        seed(client, INDEX_NAME)

        # 普通搜索：同一作者的多条都返回
        plain = client.search(index=INDEX_NAME, query={"match": {"title": "elasticsearch"}}, size=10)
        authors = [hit["_source"]["author"] for hit in plain["hits"]["hits"]]
        print(f"普通搜索作者序列={authors}（有重复作者）")

        # collapse：按 author 折叠，每个作者只保留评分最高的一条
        # inner_hits 让你额外取回每组内的其他文档
        collapsed = client.search(
            index=INDEX_NAME,
            query={"match": {"title": "elasticsearch"}},
            collapse={
                "field": "author",
                "inner_hits": {"name": "same_author", "size": 2},
            },
            size=10,
        )
        print("collapse 后每个作者一条:")
        for hit in collapsed["hits"]["hits"]:
            inner = hit["inner_hits"]["same_author"]["hits"]["total"]["value"]
            print(f"  author={hit['_source']['author']} 代表={hit['_source']['title']} 组内总数={inner}")
        print(f"折叠后返回条数={len(collapsed['hits']['hits'])}（等于唯一作者数）")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
