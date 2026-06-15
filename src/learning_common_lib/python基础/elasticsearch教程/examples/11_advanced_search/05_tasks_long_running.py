"""
目标: 用 tasks API 观察 wait_for_completion=False 提交的长任务，避免只知道“已提交”却不知道是否完成
关键 API: update_by_query(wait_for_completion=False), tasks.get, tasks.list
本例重点参数:
- wait_for_completion: False 表示立即返回 task id；这不是任务完成，只是提交成功。
- tasks.get(task_id): 查询单个任务是否 completed，并读取最终 response。
- tasks.list(actions/detailed): 查看同类运行中任务；actions 可用通配符限定 reindex 或 by_query。
Python 版本: 3.11+
运行命令: uv run python examples/11_advanced_search/05_tasks_long_running.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 提交 update_by_query 长任务，打印 task id、任务列表数量、最终更新文档数
生产提醒: reindex/update_by_query/delete_by_query 大任务应保存 task id；必要时用 tasks.cancel 取消，但取消也不是瞬时完成
"""

import os
import time

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_tasks")
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
    actions = [
        {
            "_index": index_name,
            "_id": str(i),
            "_source": {"tag": "news" if i % 2 == 0 else "blog", "archived": False, "views": i},
        }
        for i in range(30)
    ]
    helpers.bulk(client, actions, refresh="wait_for")


def wait_task_done(client: Elasticsearch, task_id: str, max_attempts: int = 20) -> dict:
    """轮询长任务；教学示例用短轮询，生产应放到后台任务或管理端。"""
    for attempt in range(1, max_attempts + 1):
        task = client.tasks.get(task_id=task_id)
        print(f"第 {attempt} 次轮询 completed={task.get('completed', False)}")
        if task.get("completed"):
            return task
        time.sleep(0.2)
    raise TimeoutError(f"任务未在预期时间内完成: {task_id}")


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=30)
    try:
        seed(client, INDEX_NAME)
        print(f"提交前 archived=True 文档数={client.count(index=INDEX_NAME, query={'term': {'archived': True}})['count']}")

        submitted = client.update_by_query(
            index=INDEX_NAME,
            query={"term": {"tag": "news"}},
            script={"source": "ctx._source.archived = true", "lang": "painless"},
            conflicts="proceed",
            refresh=True,
            wait_for_completion=False,
        )
        task_id = submitted["task"]
        print(f"已提交 task_id={task_id}")

        running = client.tasks.list(actions="*byquery", detailed=True)
        task_count = sum(len(node.get("tasks", {})) for node in running.get("nodes", {}).values())
        print(f"当前 by_query 任务数={task_count}")

        task = wait_task_done(client, task_id)
        response = task.get("response", {})
        print(f"任务完成 updated={response.get('updated')} version_conflicts={response.get('version_conflicts')}")
        print(f"完成后 archived=True 文档数={client.count(index=INDEX_NAME, query={'term': {'archived': True}})['count']}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
