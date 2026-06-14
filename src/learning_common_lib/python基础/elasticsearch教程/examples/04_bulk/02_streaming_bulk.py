"""
目标: 用 streaming_bulk 流式写入大数据集，按条处理结果并控制内存
关键 API: helpers.streaming_bulk, chunk_size, max_retries, initial_backoff
Python 版本: 3.11+
运行命令: uv run python examples/04_bulk/02_streaming_bulk.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 逐条打印进度，最终统计成功与失败数；演示对 429 的自动退避重试配置
生产提醒: streaming_bulk 适合无法一次性放进内存的大数据；用 max_retries 应对瞬时 429
"""

import os
from typing import Iterator

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_streaming_bulk")
TOTAL_DOCS = int(os.getenv("ES_TOTAL_DOCS", "200"))
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
        mappings={"properties": {"seq": {"type": "integer"}, "even": {"type": "boolean"}}},
    )


def gen_actions(index_name: str, count: int) -> Iterator[dict]:
    """惰性生成器：数据按需产出，不会一次性占满内存。"""
    for i in range(count):
        yield {"_index": index_name, "_id": f"row-{i}", "_source": {"seq": i, "even": i % 2 == 0}}


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=30)
    try:
        recreate_index(client, INDEX_NAME)

        succeeded = 0
        failed = 0
        # streaming_bulk 逐条 yield 结果；chunk_size 控制单批条数
        # max_retries + initial_backoff 让瞬时 429（写入过载）自动退避重试
        for ok, item in helpers.streaming_bulk(
            client,
            gen_actions(INDEX_NAME, TOTAL_DOCS),
            chunk_size=50,
            max_retries=3,
            initial_backoff=1,
            raise_on_error=False,
        ):
            if ok:
                succeeded += 1
            else:
                failed += 1

        client.indices.refresh(index=INDEX_NAME)
        print(f"streaming_bulk 成功={succeeded} 失败={failed}")
        print(f"索引文档总数={client.count(index=INDEX_NAME)['count']}")

        # 验证写入内容：统计 even=True 的数量
        even_count = client.count(index=INDEX_NAME, query={"term": {"even": True}})["count"]
        print(f"even=True 文档数={even_count}（应为总数的一半）")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
