"""
目标: 用 elasticsearch.dsl 高级 API 以面向对象方式建模文档和查询
关键 API: Document, Text/Keyword/Integer 字段, Search, Q, save, init
Python 版本: 3.11+
运行命令: uv run python examples/10_dsl/01_document_orm.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 用 Document 类定义 mapping 并写入，用 Search + Q 链式构建查询，打印命中标题和评分
生产提醒: DSL 适合复杂查询的可读性和复用；与底层 client.search 等价，可用 to_dict 互转排查
"""

import os

from elasticsearch import Elasticsearch
from elasticsearch.dsl import Document, Text, Keyword, Integer, Search, Q, connections


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_dsl_orm")
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


class Article(Document):
    """用类声明 mapping，字段类型直接对应 ES 字段类型。"""

    title = Text()
    tag = Keyword()
    views = Integer()

    class Index:
        name = INDEX_NAME


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    # DSL 通过 connections 注册默认连接
    connections.add_connection("default", client)
    try:
        # 重建索引：先删后用 Document 的 mapping 初始化
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        Article.init()

        # 用对象方式写入，meta.id 指定文档 id
        Article(meta={"id": "1"}, title="Elasticsearch DSL 入门", tag="search", views=10).save(refresh=True)
        Article(meta={"id": "2"}, title="Python 类型注解", tag="python", views=5).save(refresh=True)
        Article(meta={"id": "3"}, title="分布式搜索原理", tag="search", views=20).save(refresh=True)

        # Search + Q 链式构建：match 标题 + filter 标签，按 views 降序
        search = (
            Search(using=client, index=INDEX_NAME)
            .query(Q("match", title="搜索") | Q("match", title="elasticsearch"))
            .filter("term", tag="search")
            .sort("-views")
        )
        # 看等价的底层 DSL，便于排查
        print(f"生成的查询体={search.to_dict()}")

        response = search.execute()
        print(f"命中数={response.hits.total.value}")
        for hit in response:
            print(f"  id={hit.meta.id} score={hit.meta.score} views={hit.views} title={hit.title}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
