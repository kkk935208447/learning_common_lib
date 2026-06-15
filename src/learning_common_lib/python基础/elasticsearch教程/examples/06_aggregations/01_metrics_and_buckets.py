"""
目标: 掌握桶聚合（terms、range、date_histogram）和指标聚合（avg、max、stats）
关键 API: search(size=0, aggs), terms, range, avg, stats, 嵌套子聚合
本例重点参数:
- search(size=0): 只返回聚合结果，不返回 hits，降低响应体积。
- terms.field/size: field 通常用 keyword；size 默认较小，高基数字段要显式设置或用 composite。
- aggs 嵌套: 桶聚合内可再放指标聚合，表示“每组内再统计”。
Python 版本: 3.11+
运行命令: uv run python examples/06_aggregations/01_metrics_and_buckets.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 打印按分类分桶的文档数、每桶平均价格、价格区间分布
生产提醒: 聚合用 size=0 不返回命中文档；terms 默认 size=10，高基数字段要显式调大或用 composite
"""

import os

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_agg_basic")
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
                "category": {"type": "keyword"},
                "price": {"type": "integer"},
                "in_stock": {"type": "boolean"},
            }
        },
    )
    docs = [
        {"category": "book", "price": 80, "in_stock": True},
        {"category": "book", "price": 120, "in_stock": True},
        {"category": "book", "price": 200, "in_stock": False},
        {"category": "video", "price": 50, "in_stock": True},
        {"category": "video", "price": 90, "in_stock": True},
        {"category": "audio", "price": 30, "in_stock": False},
    ]
    actions = [{"_index": index_name, "_id": str(i), "_source": d} for i, d in enumerate(docs)]
    helpers.bulk(client, actions, refresh="wait_for")


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        seed(client, INDEX_NAME)

        # size=0：只要聚合结果，不返回原始命中文档
        resp = client.search(
            index=INDEX_NAME,
            size=0,
            aggs={
                # terms 桶：按 category 分组，子聚合算每组平均价
                "by_category": {
                    "terms": {"field": "category"},
                    "aggs": {"avg_price": {"avg": {"field": "price"}}},
                },
                # range 桶：自定义价格区间
                "price_ranges": {
                    "range": {
                        "field": "price",
                        "ranges": [{"to": 60}, {"from": 60, "to": 150}, {"from": 150}],
                    }
                },
                # stats 指标：一次拿到 count/min/max/avg/sum
                "price_stats": {"stats": {"field": "price"}},
            },
        )

        print("按分类分桶:")
        for bucket in resp["aggregations"]["by_category"]["buckets"]:
            print(f"  {bucket['key']}: 文档数={bucket['doc_count']} 平均价={bucket['avg_price']['value']:.1f}")

        print("价格区间分布:")
        for bucket in resp["aggregations"]["price_ranges"]["buckets"]:
            print(f"  {bucket['key']}: 文档数={bucket['doc_count']}")

        stats = resp["aggregations"]["price_stats"]
        print(f"价格统计: count={stats['count']} min={stats['min']} max={stats['max']} avg={stats['avg']:.1f}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
