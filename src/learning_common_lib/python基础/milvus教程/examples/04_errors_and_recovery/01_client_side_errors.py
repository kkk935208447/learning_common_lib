"""
目标: 演示 Milvus 调用前应优先处理的客户端错误边界
关键 API: ensure_vector, MilvusSettings.collection_name
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/04_errors_and_recovery/01_client_side_errors.py
预期现象: 打印维度错误、非法集合名、空写入跳过策略
生产提醒: 参数错误不可重试；重试只适合连接抖动、超时等可恢复故障
"""

import math
import re
from typing import Iterable


DIMENSION = 8
COLLECTION_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def ensure_vector(vector: Iterable[float], *, dimension: int) -> list[float]:
    values = [float(item) for item in vector]
    if len(values) != dimension:
        raise ValueError(f"向量维度不匹配: expected={dimension}, actual={len(values)}")
    if any(not math.isfinite(item) for item in values):
        raise ValueError("向量包含 NaN 或无穷大")
    return values


def collection_name(topic: str, *, prefix: str = "learning_milvus") -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", topic.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_").lower()
    if not normalized:
        raise ValueError("集合主题不能为空")
    name = f"{prefix}_{normalized}"
    if not COLLECTION_NAME_RE.match(name):
        raise ValueError(f"非法集合名: {name}")
    return name


def to_milvus_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return rows


def expect_value_error(label: str, func) -> None:
    try:
        func()
    except ValueError as exc:
        print(f"{label}: {exc}")
    else:
        raise AssertionError(f"{label} 应该失败")


def main() -> None:
    expect_value_error("bad_dimension", lambda: ensure_vector([1.0, 2.0], dimension=DIMENSION))
    expect_value_error("bad_collection_topic", lambda: collection_name(""))

    empty_rows = to_milvus_rows([])
    print(f"empty_write_rows={len(empty_rows)}")
    print("recovery_policy=参数错误直接失败，空批次直接跳过，连接错误交给调用层重试或降级")


if __name__ == "__main__":
    main()
