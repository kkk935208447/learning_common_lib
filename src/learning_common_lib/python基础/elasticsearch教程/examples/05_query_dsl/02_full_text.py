"""
目标: 区分 match、match_phrase、multi_match 的语义，理解全文检索的相关性评分
关键 API: match(operator/fuzziness), match_phrase(slop), multi_match(fields/type), explain
Python 版本: 3.11+
运行命令: uv run python examples/05_query_dsl/02_full_text.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: match 默认 OR、可切 AND；match_phrase 要求词序相邻；multi_match 跨字段；打印 _score 排序
生产提醒: fuzziness 容错有性能代价；multi_match 的 best_fields/most_fields 影响多字段加权方式
"""

import os

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_full_text")
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
        mappings={"properties": {"title": {"type": "text"}, "body": {"type": "text"}}},
    )
    docs = [
        {"title": "quick brown fox", "body": "the quick brown fox jumps over the lazy dog"},
        {"title": "brown bear", "body": "a brown bear walks slowly in the forest"},
        {"title": "fox news", "body": "quick updates about the world"},
    ]
    actions = [{"_index": index_name, "_id": str(i), "_source": d} for i, d in enumerate(docs)]
    helpers.bulk(client, actions, refresh="wait_for")


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        seed(client, INDEX_NAME)

        # match 默认 operator=OR：包含 quick 或 fox 都命中
        m_or = client.search(index=INDEX_NAME, query={"match": {"body": "quick fox"}})
        print(f"match OR 'quick fox' 命中={m_or['hits']['total']['value']}")

        # operator=AND：必须同时包含 quick 和 fox
        m_and = client.search(
            index=INDEX_NAME,
            query={"match": {"body": {"query": "quick fox", "operator": "and"}}},
        )
        print(f"match AND 'quick fox' 命中={m_and['hits']['total']['value']}")

        # match_phrase：要求 quick brown 作为短语相邻出现
        phrase = client.search(index=INDEX_NAME, query={"match_phrase": {"body": "quick brown"}})
        print(f"match_phrase 'quick brown' 命中={phrase['hits']['total']['value']}")

        # multi_match：在 title 和 body 两个字段里检索，best_fields 取最佳字段得分
        multi = client.search(
            index=INDEX_NAME,
            query={"multi_match": {"query": "fox", "fields": ["title^2", "body"], "type": "best_fields"}},
        )
        print("multi_match 'fox'（title 加权 2 倍）按评分排序:")
        for hit in multi["hits"]["hits"]:
            print(f"  id={hit['_id']} score={hit['_score']:.4f} title={hit['_source']['title']}")

        # fuzziness 容错：拼写成 quikc 也能命中 quick
        fuzzy = client.search(
            index=INDEX_NAME,
            query={"match": {"body": {"query": "quikc", "fuzziness": "AUTO"}}},
        )
        print(f"match fuzziness 'quikc' 命中={fuzzy['hits']['total']['value']}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
