"""
目标: 用 Point In Time (PIT) + search_after 实现稳定高效的深度翻页
关键 API: open_point_in_time, search(pit, search_after, sort), close_point_in_time
Python 版本: 3.11+
运行命令: uv run python examples/07_pagination/02_search_after_pit.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 用 PIT 锁定数据视图，借助上一页最后一条的 sort 值翻页，遍历全部文档无重复
生产提醒: PIT 占用资源，用完必须 close；翻页期间数据快照固定，不反映期间的新写入
"""

import os

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_search_after")
TOTAL_DOCS = int(os.getenv("ES_TOTAL_DOCS", "25"))
PAGE_SIZE = int(os.getenv("ES_PAGE_SIZE", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def seed(client: Elasticsearch, index_name: str, total: int) -> None:
    client.options(ignore_status=404).indices.delete(index=index_name)
    client.indices.create(
        index=index_name,
        mappings={"properties": {"seq": {"type": "integer"}}},
    )
    actions = [
        {"_index": index_name, "_id": str(i), "_source": {"seq": i}} for i in range(total)
    ]
    helpers.bulk(client, actions, refresh="wait_for")


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        seed(client, INDEX_NAME, TOTAL_DOCS)

        # 打开 PIT，锁定一个数据快照，keep_alive 是存活时间
        pit = client.open_point_in_time(index=INDEX_NAME, keep_alive="1m")
        pit_id = pit["id"]

        # 排序必须包含一个唯一字段（这里用 _shard_doc 兜底）以保证 search_after 不漏不重
        sort = [{"seq": "asc"}, {"_shard_doc": "asc"}]
        search_after = None
        seen: list[int] = []
        page = 0

        try:
            while True:
                # 用了 pit 就不传 index，pit 已绑定索引；参数全部用原生关键字传递
                kwargs = {
                    "size": PAGE_SIZE,
                    "sort": sort,
                    "pit": {"id": pit_id, "keep_alive": "1m"},
                }
                if search_after is not None:
                    kwargs["search_after"] = search_after

                resp = client.search(**kwargs)
                hits = resp["hits"]["hits"]
                if not hits:
                    break

                page += 1
                seqs = [hit["_source"]["seq"] for hit in hits]
                seen.extend(seqs)
                print(f"第 {page} 页: seq={seqs}")

                # 用最后一条的 sort 值作为下一页起点
                search_after = hits[-1]["sort"]
                # PIT 翻页过程中 id 可能更新，使用响应里返回的最新 id
                pit_id = resp.get("pit_id", pit_id)
        finally:
            # PIT 是有状态资源，必须关闭释放
            client.close_point_in_time(id=pit_id)

        print(f"共翻页 {page} 次，遍历 {len(seen)} 条，唯一={len(set(seen))} 条（应等于 {TOTAL_DOCS}）")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
