"""
目标: 理解 from/size 浅分页的代价和 10000 上限，掌握 sort 的稳定排序
关键 API: search(from_, size, sort, track_total_hits), index.max_result_window
Python 版本: 3.11+
运行命令: uv run python examples/07_pagination/01_from_size.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 逐页打印结果；演示 from+size 超过 max_result_window(默认 10000) 会报错
生产提醒: from/size 深分页代价随 from 线性增长（每个分片都要取 from+size 条），深翻页用 search_after
"""

import os

from elasticsearch import Elasticsearch, helpers
from elasticsearch import BadRequestError


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_from_size")
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
        mappings={"properties": {"seq": {"type": "integer"}, "name": {"type": "keyword"}}},
    )
    actions = [
        {"_index": index_name, "_id": str(i), "_source": {"seq": i, "name": f"item-{i:03d}"}}
        for i in range(30)
    ]
    helpers.bulk(client, actions, refresh="wait_for")


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        seed(client, INDEX_NAME)

        page_size = 10
        # 按 seq 升序稳定排序，逐页取数据
        for page in range(3):
            resp = client.search(
                index=INDEX_NAME,
                from_=page * page_size,
                size=page_size,
                sort=[{"seq": "asc"}],
                # track_total_hits=True 精确返回总数（默认超过 10000 只给下界）
                track_total_hits=True,
            )
            seqs = [hit["_source"]["seq"] for hit in resp["hits"]["hits"]]
            print(f"第 {page + 1} 页 (from={page * page_size}): seq={seqs}")

        # 演示 max_result_window 限制：from+size 超过 10000 直接报错
        try:
            client.search(index=INDEX_NAME, from_=10000, size=10, sort=[{"seq": "asc"}])
        except BadRequestError as exc:
            print(f"from=10000 触发上限错误: {exc.error}")
            print("结论: 深翻页不要用 from/size，改用 search_after")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
