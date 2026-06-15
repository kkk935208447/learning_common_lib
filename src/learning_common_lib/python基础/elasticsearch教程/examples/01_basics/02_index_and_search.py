"""
目标: 用最少代码跑通 create index → index doc → refresh → search → delete 完整闭环
关键 API: indices.create, index, indices.refresh, search, indices.delete
本例重点参数:
- indices.create(index/mappings): index 是索引名，mappings 决定字段类型；字段类型创建后不能原地修改。
- index(index/id/document): id 由业务主键派生可保证幂等；document 字段必须与 mapping 预期一致。
- search(query/size): query 决定召回，size 控制返回 topN；不设置 size 时默认只返回少量命中。
Python 版本: 3.11+
运行命令: uv run python examples/01_basics/02_index_and_search.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 打印写入结果、命中数量、top hit 的标题和评分
生产提醒: 示例结束会删除教程专用索引 learning_es_quickstart，不影响其他索引
"""

import os

from elasticsearch import Elasticsearch


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
# 教程统一使用 learning_es_ 前缀，清理只作用于该索引
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_quickstart")
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def recreate_index(client: Elasticsearch, index_name: str) -> None:
    """重建教程索引，保证示例可重复运行。"""
    # ignore_status 让删除在索引不存在时不报错
    client.options(ignore_status=404).indices.delete(index=index_name)
    client.indices.create(
        index=index_name,
        mappings={
            "properties": {
                # text 走分词，适合全文检索
                "title": {"type": "text"},
                # keyword 不分词，适合精确过滤和聚合
                "tag": {"type": "keyword"},
            }
        },
    )


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        recreate_index(client, INDEX_NAME)

        # 写入两条文档，指定 id 保证幂等重写
        client.index(index=INDEX_NAME, id="1", document={"title": "Elasticsearch 入门指南", "tag": "search"})
        client.index(index=INDEX_NAME, id="2", document={"title": "Python 异步编程", "tag": "python"})

        # 默认写入到 refresh 之间存在 1 秒可见延迟；refresh 强制刷新让文档立即可搜
        client.indices.refresh(index=INDEX_NAME)

        resp = client.search(
            index=INDEX_NAME,
            query={"match": {"title": "elasticsearch"}},
            size=5,
        )
        total = resp["hits"]["total"]["value"]
        print(f"index={INDEX_NAME}")
        print(f"total_hits={total}")
        for hit in resp["hits"]["hits"]:
            print(f"hit id={hit['_id']} score={hit['_score']:.4f} title={hit['_source']['title']}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
