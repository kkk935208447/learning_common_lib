"""
目标: 自定义分析器，并用 multi-field 让同一字段既能全文检索又能精确聚合
关键 API: indices.create(settings.analysis), indices.analyze, fields(子字段)
Python 版本: 3.11+
运行命令: uv run python examples/02_mapping_analysis/02_custom_analyzer.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 自定义分析器去除 html、转小写、去停用词；title.raw 子字段保留原值用于聚合
生产提醒: 中文检索需要 IK 等分词插件，标准分析器对中文是按单字切分，召回质量有限
"""

import os

from elasticsearch import Elasticsearch


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_custom_analyzer")
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
        settings={
            "analysis": {
                "analyzer": {
                    # 自定义分析器：先剥离 html 标签，再标准分词、转小写、去英文停用词
                    "clean_english": {
                        "type": "custom",
                        "char_filter": ["html_strip"],
                        "tokenizer": "standard",
                        "filter": ["lowercase", "stop"],
                    }
                }
            }
        },
        mappings={
            "properties": {
                "title": {
                    "type": "text",
                    "analyzer": "clean_english",
                    # multi-field：title 走分词检索，title.raw 是 keyword 用于排序和聚合
                    "fields": {"raw": {"type": "keyword"}},
                }
            }
        },
    )


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        recreate_index(client, INDEX_NAME)

        # 直接验证自定义分析器：html 被剥离，the 作为停用词被去掉
        analyzed = client.indices.analyze(
            index=INDEX_NAME,
            analyzer="clean_english",
            text="<p>The Quick Search</p>",
        )
        tokens = [item["token"] for item in analyzed["tokens"]]
        print(f"自定义分析器分词={tokens}")

        client.index(index=INDEX_NAME, id="1", document={"title": "The Distributed Search Engine"}, refresh="wait_for")

        # 用分词字段做全文检索
        hit = client.search(index=INDEX_NAME, query={"match": {"title": "search"}})
        print(f"match 'search' 命中数={hit['hits']['total']['value']}")

        # 用 .raw 子字段做精确聚合，拿到未分词的完整原值
        agg = client.search(
            index=INDEX_NAME,
            size=0,
            aggs={"titles": {"terms": {"field": "title.raw"}}},
        )
        buckets = [(b["key"], b["doc_count"]) for b in agg["aggregations"]["titles"]["buckets"]]
        print(f"title.raw 聚合桶={buckets}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
