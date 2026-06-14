"""
目标: 用 helpers.bulk 高效批量写入，理解 actions 结构和错误统计
关键 API: helpers.bulk, _op_type, _index, _id, raise_on_error
Python 版本: 3.11+
运行命令: uv run python examples/04_bulk/01_bulk_helpers.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 打印成功写入条数，并演示一条非法文档被收集到 errors 而不中断整体
生产提醒: 单批 actions 控制在几 MB / 几千条；过大批次会触发 429，需要分块和退避重试
"""

import os
from typing import Iterator

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_bulk")
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
        mappings={"properties": {"title": {"type": "text"}, "seq": {"type": "integer"}}},
    )


def gen_actions(index_name: str, count: int) -> Iterator[dict]:
    """生成 bulk action：每条带 _index 和 _id，默认 _op_type=index。"""
    for i in range(count):
        yield {
            "_index": index_name,
            "_id": f"doc-{i}",
            "_source": {"title": f"文档 {i}", "seq": i},
        }


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=30)
    try:
        recreate_index(client, INDEX_NAME)

        # 正常批量写入：bulk 返回 (成功数, 错误列表)
        success, errors = helpers.bulk(client, gen_actions(INDEX_NAME, 50), refresh="wait_for")
        print(f"bulk 成功写入={success} 错误数={len(errors) if isinstance(errors, list) else errors}")

        # 演示部分失败：seq 字段写入非整数会被单条拒绝
        bad_actions = [
            {"_index": INDEX_NAME, "_id": "ok", "_source": {"title": "正常", "seq": 999}},
            {"_index": INDEX_NAME, "_id": "bad", "_source": {"title": "非法", "seq": "not-an-int"}},
        ]
        # raise_on_error=False：不因单条失败抛异常，而是收集到 errors 里
        ok_count, item_errors = helpers.bulk(
            client, bad_actions, raise_on_error=False, refresh="wait_for"
        )
        print(f"含非法文档批次 成功={ok_count} 失败={len(item_errors)}")
        if item_errors:
            first = item_errors[0]["index"]
            print(f"失败原因类型={first['error']['type']}")

        client.indices.refresh(index=INDEX_NAME)
        total = client.count(index=INDEX_NAME)["count"]
        print(f"最终文档总数={total}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
