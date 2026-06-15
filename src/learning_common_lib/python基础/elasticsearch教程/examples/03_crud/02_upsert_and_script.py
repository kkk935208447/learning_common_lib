"""
目标: 用 upsert 实现幂等写入，用 script 做原子累加，避免读-改-写竞态
关键 API: update(doc + doc_as_upsert), update(script + upsert), get
本例重点参数:
- update(doc/doc_as_upsert): 文档存在时局部更新，不存在时用 doc 插入，适合可重跑导入。
- update(script/upsert): script 在服务端执行，适合计数累加；upsert 提供初始文档。
- script.lang/source/params: 生产脚本应参数化，避免拼接用户输入。
Python 版本: 3.11+
运行命令: uv run python examples/03_crud/02_upsert_and_script.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 首次 upsert 创建文档，二次 script 累加 views，多次运行结果稳定可预期
生产提醒: doc_as_upsert 适合“存在则更新、不存在则插入”；计数类更新优先用 script 保证原子性
"""

import os

from elasticsearch import Elasticsearch


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_upsert_script")
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
        mappings={"properties": {"name": {"type": "keyword"}, "views": {"type": "long"}}},
    )


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        recreate_index(client, INDEX_NAME)

        # doc_as_upsert=True：文档不存在则用 doc 创建，存在则用 doc 部分更新
        for _ in range(2):
            client.update(
                index=INDEX_NAME,
                id="page-1",
                doc={"name": "home", "views": 0},
                doc_as_upsert=True,
                refresh="wait_for",
            )
        after_upsert = client.get(index=INDEX_NAME, id="page-1")["_source"]
        print(f"两次 doc_as_upsert 后={after_upsert}（重复执行不会重复累加）")

        # script + upsert：原子累加。upsert 提供文档不存在时的初始值
        for _ in range(3):
            client.update(
                index=INDEX_NAME,
                id="page-1",
                script={
                    "source": "ctx._source.views += params.delta",
                    "lang": "painless",
                    "params": {"delta": 1},
                },
                upsert={"name": "home", "views": 1},
                refresh="wait_for",
            )
        after_script = client.get(index=INDEX_NAME, id="page-1")["_source"]
        print(f"三次 script 累加后 views={after_script['views']}（每次原子 +1）")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
