"""
目标: 掌握单文档 CRUD：index、get、update（部分更新）、delete 与 exists
关键 API: index, get, update(doc), exists, delete
本例重点参数:
- index(index/id/document/refresh): 指定 id 便于幂等覆盖；refresh 只在教学或强一致场景使用。
- update(doc): 只更新 doc 中出现的字段，不会替换整篇文档。
- exists(index/id): 判断文档是否存在，适合替代可预期 404 异常控制流。
Python 版本: 3.11+
运行命令: uv run python examples/03_crud/01_document_crud.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 依次打印创建结果、读取结果、部分更新后的文档、删除后 exists=False
生产提醒: update 是“读-改-写”，并非原子字段累加；高并发累加应用 script 或乐观锁
"""

import os

from elasticsearch import Elasticsearch


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_doc_crud")
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
                "title": {"type": "text"},
                "status": {"type": "keyword"},
                "views": {"type": "integer"},
            }
        },
    )


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        recreate_index(client, INDEX_NAME)

        # 创建：指定 id 时同 id 重复写入会覆盖，result=created/updated
        created = client.index(
            index=INDEX_NAME,
            id="doc-1",
            document={"title": "Elasticsearch CRUD", "status": "draft", "views": 0},
            refresh="wait_for",
        )
        print(f"index result={created['result']} version={created['_version']}")

        # 读取整条文档
        got = client.get(index=INDEX_NAME, id="doc-1")
        print(f"get source={got['_source']}")

        # 部分更新：只传变化的字段，未传字段保持不变
        client.update(
            index=INDEX_NAME,
            id="doc-1",
            doc={"status": "published", "views": 10},
            refresh="wait_for",
        )
        updated = client.get(index=INDEX_NAME, id="doc-1")
        print(f"after update source={updated['_source']} version={updated['_version']}")

        # 删除并确认不存在
        client.delete(index=INDEX_NAME, id="doc-1", refresh="wait_for")
        print(f"exists after delete={client.exists(index=INDEX_NAME, id='doc-1')}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
