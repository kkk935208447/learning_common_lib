"""
目标: 认识客户端常见异常类型，写出可区分处理的错误恢复代码
关键 API: NotFoundError, BadRequestError, ConflictError, ApiError, exists
本例重点参数:
- client.options(ignore_status=404): 只用于可预期状态码，避免清理或探测逻辑抛异常。
- exists(index/id): 轻量判断文档是否存在，替代正常分支里的 404 异常。
- ApiError.meta.status: 区分 4xx 请求问题和 5xx/超时问题，决定是否重试。
Python 版本: 3.11+
运行命令: uv run python examples/08_errors_recovery/01_exception_types.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 分别触发并捕获 404（文档不存在）、400（mapping 冲突），打印异常类型和 meta.status
生产提醒: 用 exists/ignore_status 处理可预期的 404，用 try/except 区分 4xx 客户端错误与 5xx 服务端错误
"""

import os

from elasticsearch import Elasticsearch
from elasticsearch import NotFoundError, BadRequestError


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_exceptions")
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
        mappings={"properties": {"count": {"type": "integer"}}},
    )


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        recreate_index(client, INDEX_NAME)

        # 1) NotFoundError：读取不存在的文档抛 404
        try:
            client.get(index=INDEX_NAME, id="missing")
        except NotFoundError as exc:
            print(f"捕获 NotFoundError status={exc.meta.status} 含义=文档不存在")

        # 推荐做法：可预期的不存在用 exists 探测，避免异常控制流
        print(f"用 exists 判断缺失文档={client.exists(index=INDEX_NAME, id='missing')}")

        # 2) BadRequestError：写入与 mapping 冲突的类型抛 400
        try:
            client.index(index=INDEX_NAME, id="1", document={"count": "这不是整数"})
        except BadRequestError as exc:
            print(f"捕获 BadRequestError status={exc.meta.status} 类型={exc.error}")

        # 3) ignore_status：批量清理时容忍 404，不抛异常
        resp = client.options(ignore_status=404).indices.delete(index="learning_es_not_exist")
        print(f"删除不存在索引 ignore_status=404 返回 status={resp.meta.status}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
