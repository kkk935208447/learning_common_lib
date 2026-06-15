"""
目标: 用 AsyncElasticsearch 并发执行多个搜索，理解异步客户端的生命周期
关键 API: AsyncElasticsearch, await client.search, asyncio.gather, await client.close
本例重点参数:
- AsyncElasticsearch(hosts/request_timeout): 异步客户端也要显式超时，并在应用生命周期内复用。
- async with: 退出时自动关闭连接池，避免 unclosed connector。
- asyncio.gather: 并发等待多个查询；生产还要配合 Semaphore 做背压。
Python 版本: 3.11+
运行命令: uv run python examples/09_production/02_async_client.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 并发发起多个查询，打印每个查询命中数；演示 async with 自动关闭连接
生产提醒: 异步客户端连接池仍有上限；并发不等于无限，仍需配合超时和背压控制
"""

import asyncio
import os

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_async")
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


async def seed(client: AsyncElasticsearch, index_name: str) -> None:
    await client.options(ignore_status=404).indices.delete(index=index_name)
    await client.indices.create(
        index=index_name,
        mappings={"properties": {"title": {"type": "text"}, "tag": {"type": "keyword"}}},
    )
    docs = [
        {"title": "Elasticsearch 异步检索", "tag": "search"},
        {"title": "asyncio 并发模型", "tag": "python"},
        {"title": "分布式系统设计", "tag": "search"},
    ]
    actions = [{"_index": index_name, "_id": str(i), "_source": d} for i, d in enumerate(docs)]
    # async_bulk 是 bulk 的异步版本
    await async_bulk(client, actions, refresh="wait_for")


async def search_tag(client: AsyncElasticsearch, index_name: str, tag: str) -> tuple[str, int]:
    resp = await client.search(index=index_name, query={"term": {"tag": tag}})
    return tag, resp["hits"]["total"]["value"]


async def main() -> None:
    ensure_local_no_proxy()
    # async with 在退出时自动关闭连接，避免泄漏
    async with AsyncElasticsearch(ES_HOST, request_timeout=10) as client:
        try:
            await seed(client, INDEX_NAME)

            # asyncio.gather 并发发起多个独立查询
            results = await asyncio.gather(
                search_tag(client, INDEX_NAME, "search"),
                search_tag(client, INDEX_NAME, "python"),
                search_tag(client, INDEX_NAME, "search"),
            )
            for tag, count in results:
                print(f"并发查询 tag={tag} 命中={count}")
        finally:
            await client.options(ignore_status=404).indices.delete(index=INDEX_NAME)


if __name__ == "__main__":
    asyncio.run(main())
