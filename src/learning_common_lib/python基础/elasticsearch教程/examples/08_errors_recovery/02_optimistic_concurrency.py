"""
目标: 用 if_seq_no/if_primary_term 实现乐观并发控制，安全处理版本冲突
关键 API: index(if_seq_no, if_primary_term), get(_seq_no/_primary_term), ConflictError
本例重点参数:
- get(...): 响应中的 `_seq_no` 和 `_primary_term` 是文档当前版本凭证。
- index(if_seq_no/if_primary_term): 只有版本匹配才写入，过期版本触发 409。
- ConflictError: 捕获后重读最新文档，再基于新版本重试。
Python 版本: 3.11+
运行命令: uv run python examples/08_errors_recovery/02_optimistic_concurrency.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 基于过期版本写入触发 409 ConflictError；重新读取最新版本后重试成功
生产提醒: 并发更新同一文档时用 _seq_no + _primary_term 做 CAS，比全局锁更轻量
"""

import os

from elasticsearch import Elasticsearch
from elasticsearch import ConflictError


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_occ")
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
        mappings={"properties": {"balance": {"type": "integer"}}},
    )


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        recreate_index(client, INDEX_NAME)
        client.index(index=INDEX_NAME, id="acc-1", document={"balance": 100}, refresh="wait_for")

        # 客户端 A 读到文档，记录乐观锁坐标 _seq_no / _primary_term
        doc_a = client.get(index=INDEX_NAME, id="acc-1")
        seq_a, term_a = doc_a["_seq_no"], doc_a["_primary_term"]

        # 客户端 B 先一步更新成功，文档 _seq_no 前进
        client.index(index=INDEX_NAME, id="acc-1", document={"balance": 200}, refresh="wait_for")

        # 客户端 A 用过期的 seq/term 写入，触发 409 冲突
        try:
            client.index(
                index=INDEX_NAME,
                id="acc-1",
                document={"balance": 150},
                if_seq_no=seq_a,
                if_primary_term=term_a,
            )
        except ConflictError as exc:
            print(f"捕获 ConflictError status={exc.meta.status} 含义=版本已被他人修改")

        # 恢复策略：重新读取最新版本，再用新坐标重试
        latest = client.get(index=INDEX_NAME, id="acc-1")
        result = client.index(
            index=INDEX_NAME,
            id="acc-1",
            document={"balance": latest["_source"]["balance"] + 50},
            if_seq_no=latest["_seq_no"],
            if_primary_term=latest["_primary_term"],
            refresh="wait_for",
        )
        final = client.get(index=INDEX_NAME, id="acc-1")["_source"]
        print(f"重试成功 result={result['result']} 最终 balance={final['balance']}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
