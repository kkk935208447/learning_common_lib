"""
目标: 用 update_by_query 和 delete_by_query 按条件批量改/删，避免逐条往返
关键 API: update_by_query(script), delete_by_query, conflicts="proceed", refresh
本例重点参数:
- update_by_query(query/script): 按快照匹配后批量更新，script 在服务端执行。
- delete_by_query(query): 按条件批量删除；生产必须先用 query/count 验证影响范围。
- conflicts/refresh: conflicts="proceed" 跳过版本冲突继续；refresh=True 便于示例立即观察。
Python 版本: 3.11+
运行命令: uv run python examples/11_advanced_search/04_by_query_ops.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 按 tag 批量给文档加标记，再按条件批量删除，打印受影响文档数
生产提醒: by_query 是重操作，按快照执行；并发写易冲突，用 conflicts="proceed" 跳过冲突继续
"""

import os

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_by_query")
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
                "tag": {"type": "keyword"},
                "archived": {"type": "boolean"},
                "views": {"type": "long"},
            }
        },
    )
    docs = [
        {"tag": "news", "archived": False, "views": 10},
        {"tag": "news", "archived": False, "views": 20},
        {"tag": "blog", "archived": False, "views": 5},
        {"tag": "blog", "archived": False, "views": 8},
    ]
    actions = [{"_index": index_name, "_id": str(i), "_source": d} for i, d in enumerate(docs)]
    helpers.bulk(client, actions, refresh="wait_for")


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=30)
    try:
        seed(client, INDEX_NAME)

        # update_by_query + script：把所有 tag=news 的文档 archived 置为 True
        # conflicts="proceed"：遇到版本冲突跳过该条继续，而不是整体失败
        upd = client.update_by_query(
            index=INDEX_NAME,
            query={"term": {"tag": "news"}},
            script={"source": "ctx._source.archived = true", "lang": "painless"},
            conflicts="proceed",
            refresh=True,
        )
        print(f"update_by_query 更新文档数={upd['updated']} 冲突数={upd['version_conflicts']}")
        archived_count = client.count(index=INDEX_NAME, query={"term": {"archived": True}})["count"]
        print(f"archived=True 文档数={archived_count}")

        # delete_by_query：删除低于阈值的文档
        dele = client.delete_by_query(
            index=INDEX_NAME,
            query={"range": {"views": {"lt": 10}}},
            conflicts="proceed",
            refresh=True,
        )
        print(f"delete_by_query 删除文档数={dele['deleted']}")
        print(f"剩余文档总数={client.count(index=INDEX_NAME)['count']}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
