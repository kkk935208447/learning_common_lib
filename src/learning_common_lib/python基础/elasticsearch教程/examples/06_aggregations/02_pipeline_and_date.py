"""
目标: 在查询上下文里做聚合，并用 date_histogram + 管道聚合做时间序列分析
关键 API: search(query+aggs), date_histogram, cumulative_sum, bucket 内嵌指标
Python 版本: 3.11+
运行命令: uv run python examples/06_aggregations/02_pipeline_and_date.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 打印按天分桶的销量、累计销量（管道聚合），并演示聚合受 query 过滤影响
生产提醒: date_histogram 的 calendar_interval 受时区影响；管道聚合在已有桶上二次计算，注意顺序依赖
"""

import os

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_agg_pipeline")
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
                "sold_at": {"type": "date"},
                "amount": {"type": "integer"},
                "region": {"type": "keyword"},
            }
        },
    )
    docs = [
        {"sold_at": "2026-06-01", "amount": 10, "region": "north"},
        {"sold_at": "2026-06-01", "amount": 20, "region": "south"},
        {"sold_at": "2026-06-02", "amount": 15, "region": "north"},
        {"sold_at": "2026-06-03", "amount": 25, "region": "north"},
        {"sold_at": "2026-06-03", "amount": 5, "region": "south"},
    ]
    actions = [{"_index": index_name, "_id": str(i), "_source": d} for i, d in enumerate(docs)]
    helpers.bulk(client, actions, refresh="wait_for")


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        seed(client, INDEX_NAME)

        # 聚合在 query 上下文里执行：只统计 region=north 的数据
        resp = client.search(
            index=INDEX_NAME,
            size=0,
            query={"term": {"region": "north"}},
            aggs={
                "sales_per_day": {
                    # 按天分桶
                    "date_histogram": {"field": "sold_at", "calendar_interval": "day"},
                    "aggs": {
                        # 每天销量合计
                        "daily_amount": {"sum": {"field": "amount"}},
                        # 管道聚合：基于每天 daily_amount 计算累计销量
                        "cumulative_amount": {"cumulative_sum": {"buckets_path": "daily_amount"}},
                    },
                }
            },
        )

        print("region=north 每日销量与累计销量:")
        for bucket in resp["aggregations"]["sales_per_day"]["buckets"]:
            day = bucket["key_as_string"][:10]
            daily = bucket["daily_amount"]["value"]
            cumulative = bucket["cumulative_amount"]["value"]
            print(f"  {day}: 当日={daily:.0f} 累计={cumulative:.0f}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
