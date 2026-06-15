"""
目标: 理解 text 与 keyword 的本质差别，看清分词如何影响检索和聚合
关键 API: indices.create(mappings), indices.analyze, search(term/match)
本例重点参数:
- mappings.properties.type: text 会分词用于全文检索，keyword 不分词用于过滤、排序和聚合。
- indices.analyze(index/analyzer/text): 验证文本实际 token，排查“term 查不到”的第一步。
- search(query): term 要求精确 token，match 会先分析查询文本后再匹配。
Python 版本: 3.11+
运行命令: uv run python examples/02_mapping_analysis/01_field_types.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 同一份内容用 text 字段 match 命中，用 keyword 字段 term 才能精确命中
生产提醒: mapping 一旦创建，字段类型不可修改；改类型只能新建索引再 reindex
"""

import os

from elasticsearch import Elasticsearch


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_field_types")
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def recreate_index(client: Elasticsearch, index_name: str) -> None:
    client.options(ignore_status=404).indices.delete(index=index_name)
    client.indices.create(
        index=index_name,
        mappings={
            "properties": {
                # 同一份分类文本同时映射为 text 和 keyword，对比两种检索行为
                "category_text": {"type": "text"},
                "category_keyword": {"type": "keyword"},
                "views": {"type": "integer"},
                "published_at": {"type": "date"},
            }
        },
    )


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        recreate_index(client, INDEX_NAME)
        doc = {
            "category_text": "Search Engine",
            "category_keyword": "Search Engine",
            "views": 120,
            "published_at": "2026-06-14",
        }
        client.index(index=INDEX_NAME, id="1", document=doc, refresh="wait_for")

        # text 字段被分词为 search / engine，小写匹配也能命中
        text_hit = client.search(index=INDEX_NAME, query={"match": {"category_text": "search"}})
        print(f"text 字段 match 'search' 命中数={text_hit['hits']['total']['value']}")

        # keyword 字段是整体值，term 必须完全相等（大小写敏感）才命中
        kw_exact = client.search(index=INDEX_NAME, query={"term": {"category_keyword": "Search Engine"}})
        print(f"keyword 字段 term 'Search Engine' 命中数={kw_exact['hits']['total']['value']}")

        kw_wrong = client.search(index=INDEX_NAME, query={"term": {"category_keyword": "search"}})
        print(f"keyword 字段 term 'search'（小写）命中数={kw_wrong['hits']['total']['value']}")

        # 直接看分析器如何切词，理解上面命中差异的根因
        analyzed = client.indices.analyze(index=INDEX_NAME, field="category_text", text="Search Engine")
        tokens = [item["token"] for item in analyzed["tokens"]]
        print(f"text 字段分词结果={tokens}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
