"""
目标: 演示教程集合命名策略，避免清理逻辑误删真实集合
关键 API: MilvusSettings.collection_name
本例重点参数:
- collection_prefix: 教程统一使用 learning_milvus 前缀，清理逻辑只能处理受控命名空间。
- topic: 会归一化为 collection 名的一部分，不能为空，且最终名称必须满足 Milvus 命名规则。
- COLLECTION_NAME_RE: 限制首字符、长度和可用字符，避免运行时才由 Milvus 报错。
流程索引: roadmap.md#milvus-工程使用流程
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/02_schema_index/02_collection_name_policy.py
预期现象: 打印带 learning_milvus 前缀的合法集合名，并展示非法主题的错误
生产提醒: 集合名应带业务或租户前缀，批量清理只能作用于受控前缀
"""

import os
import re
from dataclasses import dataclass


COLLECTION_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


@dataclass(frozen=True)
class MilvusSettings:
    collection_prefix: str = "learning_milvus"

    def collection_name(self, topic: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_]", "_", topic.strip())
        normalized = re.sub(r"_+", "_", normalized).strip("_").lower()
        if not normalized:
            raise ValueError("集合主题不能为空")
        name = f"{self.collection_prefix}_{normalized}"
        if not COLLECTION_NAME_RE.match(name):
            raise ValueError(f"非法集合名: {name}")
        return name


def load_settings() -> MilvusSettings:
    return MilvusSettings(collection_prefix=os.getenv("MILVUS_COLLECTION_PREFIX", "learning_milvus"))


def main() -> None:
    settings = load_settings()
    print(f"quickstart_collection={settings.collection_name('Quick Start')}")
    print(f"filter_collection={settings.collection_name('filter-and-crud')}")

    try:
        settings.collection_name("!!!")
    except ValueError as exc:
        print(f"empty_topic_error={exc}")
    else:
        raise AssertionError("空集合主题应当失败")


if __name__ == "__main__":
    main()
