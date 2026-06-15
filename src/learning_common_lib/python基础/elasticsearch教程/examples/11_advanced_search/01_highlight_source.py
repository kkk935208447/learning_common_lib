"""
目标: 用 highlight 高亮命中片段，用 _source 过滤裁剪返回字段，降低响应体积
关键 API: search(highlight), pre_tags/post_tags/fragment_size, source(includes/excludes)
本例重点参数:
- highlight.fields: 指定要高亮的 text 字段；高亮会增加 CPU 和响应体积。
- pre_tags/post_tags/fragment_size: 控制命中片段包裹标签和长度，前端需统一转义策略。
- source/includes/excludes: 裁剪 `_source` 返回字段，大文档检索应默认只取必要字段。
Python 版本: 3.11+
运行命令: uv run python examples/11_advanced_search/01_highlight_source.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 打印带 <em> 标记的高亮片段，并演示只返回指定字段
生产提醒: 大文档只取需要的字段能显著降低网络和反序列化开销；高亮对长文本有 CPU 代价
"""

import os

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_highlight")
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
        mappings={
            "properties": {
                "title": {"type": "text"},
                "body": {"type": "text"},
                "author": {"type": "keyword"},
            }
        },
    )
    docs = [
        {
            "title": "Elasticsearch 全文检索",
            "body": "Elasticsearch 基于 Lucene 倒排索引实现高效全文检索和相关性排序。",
            "author": "alice",
        },
        {
            "title": "向量检索入门",
            "body": "现代检索系统常把 Elasticsearch 的关键词检索和向量检索结合做混合召回。",
            "author": "bob",
        },
    ]
    actions = [{"_index": index_name, "_id": str(i), "_source": d} for i, d in enumerate(docs)]
    helpers.bulk(client, actions, refresh="wait_for")


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        seed(client, INDEX_NAME)

        # highlight：在命中字段里用标签包裹匹配词，fragment_size 控制片段长度
        resp = client.search(
            index=INDEX_NAME,
            query={"match": {"body": "检索"}},
            highlight={
                "pre_tags": ["<em>"],
                "post_tags": ["</em>"],
                "fields": {"body": {"fragment_size": 50, "number_of_fragments": 1}},
            },
        )
        print("高亮片段:")
        for hit in resp["hits"]["hits"]:
            fragments = hit.get("highlight", {}).get("body", [])
            print(f"  id={hit['_id']} highlight={fragments}")

        # _source 过滤：只返回 title，省去 body 的传输和反序列化
        only_title = client.search(
            index=INDEX_NAME,
            query={"match_all": {}},
            source={"includes": ["title"]},
            size=2,
        )
        print("只返回 title 字段:")
        for hit in only_title["hits"]["hits"]:
            print(f"  id={hit['_id']} source_keys={list(hit['_source'].keys())}")

        # excludes：返回除 body 外的所有字段
        without_body = client.search(
            index=INDEX_NAME,
            query={"match_all": {}},
            source={"excludes": ["body"]},
            size=1,
        )
        print(f"排除 body 后字段={list(without_body['hits']['hits'][0]['_source'].keys())}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
