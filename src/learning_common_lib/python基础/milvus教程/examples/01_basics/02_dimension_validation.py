"""
目标: 演示向量维度错误和非法数值应在客户端边界失败
关键 API: ensure_vector, l2_normalize
本例重点参数:
- ensure_vector(vector, dimension): dimension 必须和 collection 的 FLOAT_VECTOR dim 完全一致。
- l2_normalize(vector, dimension): 归一化前要拒绝空向量、NaN、无穷大和零向量。
- ValueError: 这些是数据质量错误，应在入库前失败，不应交给 Milvus 或重试逻辑处理。
流程索引: roadmap.md#milvus-工程使用流程
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/01_basics/02_dimension_validation.py
预期现象: 打印三个可预期的 ValueError 场景，并展示一个合法向量
生产提醒: 维度、NaN、零向量问题属于数据质量错误，不应通过重试解决
"""

from math import nan
import math
from typing import Iterable


def ensure_vector(vector: Iterable[float], *, dimension: int) -> list[float]:
    values = [float(item) for item in vector]
    if len(values) != dimension:
        raise ValueError(f"向量维度不匹配: expected={dimension}, actual={len(values)}")
    if not values:
        raise ValueError("向量不能为空")
    if any(not math.isfinite(item) for item in values):
        raise ValueError("向量包含 NaN 或无穷大")
    return values


def l2_normalize(vector: Iterable[float], *, dimension: int) -> list[float]:
    values = ensure_vector(vector, dimension=dimension)
    norm = math.sqrt(sum(item * item for item in values))
    if norm == 0:
        raise ValueError("零向量不能归一化")
    return [item / norm for item in values]


def show_expected_error(label: str, func) -> None:
    try:
        func()
    except ValueError as exc:
        print(f"{label}: {exc}")
    else:
        raise AssertionError(f"{label} 应该失败")


def main() -> None:
    valid = ensure_vector([1, 2, 3, 4], dimension=4)
    normalized = l2_normalize(valid, dimension=4)
    print(f"valid_dimension={len(valid)}")
    print(f"normalized_norm={sum(item * item for item in normalized):.4f}")

    show_expected_error("维度错误", lambda: ensure_vector([1, 2, 3], dimension=4))
    show_expected_error("非法数值", lambda: ensure_vector([1, 2, nan, 4], dimension=4))
    show_expected_error("零向量", lambda: l2_normalize([0, 0, 0, 0], dimension=4))


if __name__ == "__main__":
    main()
