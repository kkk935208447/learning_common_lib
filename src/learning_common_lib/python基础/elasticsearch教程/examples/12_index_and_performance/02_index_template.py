"""
目标: 用 index template 让按命名规则自动创建的索引统一套用 mapping 和 settings
关键 API: indices.put_index_template, index_patterns, template, indices.delete_index_template
Python 版本: 3.11+
运行命令: uv run python examples/12_index_and_performance/02_index_template.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: 创建模板后，匹配命名的新索引自动带上预定义 mapping，无需逐个声明
生产提醒: 模板适合时序/日志这类按日期滚动的索引族；用 priority 解决多模板匹配冲突
"""

import os

from elasticsearch import Elasticsearch


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
TEMPLATE_NAME = os.getenv("ES_TEMPLATE", "learning_es_logs_template")
# 模板按这个模式匹配索引名，匹配到的新索引自动套用下面的 template
INDEX_PATTERN = os.getenv("ES_INDEX_PATTERN", "learning_es_logs-*")
SAMPLE_INDEX = os.getenv("ES_SAMPLE_INDEX", "learning_es_logs-2026.06.14")
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        client.options(ignore_status=404).indices.delete(index=SAMPLE_INDEX)
        client.options(ignore_status=404).indices.delete_index_template(name=TEMPLATE_NAME)

        # 定义模板：所有匹配 learning_es_logs-* 的索引都套用这套 settings + mappings
        client.indices.put_index_template(
            name=TEMPLATE_NAME,
            index_patterns=[INDEX_PATTERN],
            # priority 越高优先级越高，多模板匹配同一索引时用它决断
            priority=100,
            template={
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {
                    "properties": {
                        "@timestamp": {"type": "date"},
                        "level": {"type": "keyword"},
                        "message": {"type": "text"},
                    }
                },
            },
        )
        print(f"已创建 index template={TEMPLATE_NAME} 匹配={INDEX_PATTERN}")

        # 直接写入一条文档，索引被自动创建并套用模板，无需显式 create
        client.index(
            index=SAMPLE_INDEX,
            id="1",
            document={"@timestamp": "2026-06-14T10:00:00", "level": "ERROR", "message": "磁盘空间不足"},
            refresh="wait_for",
        )

        # 验证自动创建的索引带上了模板里的 mapping
        mapping = client.indices.get_mapping(index=SAMPLE_INDEX)[SAMPLE_INDEX]["mappings"]["properties"]
        print(f"自动创建索引={SAMPLE_INDEX}")
        print(f"自动套用字段类型: level={mapping['level']['type']} @timestamp={mapping['@timestamp']['type']}")

        # 用 level 这个 keyword 字段直接过滤，证明 mapping 生效
        hit = client.count(index=SAMPLE_INDEX, query={"term": {"level": "ERROR"}})["count"]
        print(f"level=ERROR 文档数={hit}")
    finally:
        client.options(ignore_status=404).indices.delete(index=SAMPLE_INDEX)
        client.options(ignore_status=404).indices.delete_index_template(name=TEMPLATE_NAME)
        client.close()


if __name__ == "__main__":
    main()
