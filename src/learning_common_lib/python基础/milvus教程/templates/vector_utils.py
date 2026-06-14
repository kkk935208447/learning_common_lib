"""
解决什么问题: 在写入 Milvus 前校验向量维度、数值和归一化策略
输入输出约定: 输入 LangChain Document 或 Python list[float]，输出可直接写入 Milvus 的行数据
失败策略: 对维度不匹配、空向量、非有限数字抛出 ValueError
适用边界: 教程和小型 RAG 服务；生产环境应把校验放在 embedding 生成边界
"""

from __future__ import annotations

import math
from typing import Iterable, cast

from langchain_core.documents import Document


def ensure_vector(vector: Iterable[float], *, dimension: int) -> list[float]:
    """校验向量维度和数值，返回 float 列表。"""
    values = [float(item) for item in vector]
    if len(values) != dimension:
        raise ValueError(f"向量维度不匹配: expected={dimension}, actual={len(values)}")
    if not values:
        raise ValueError("向量不能为空")
    if any(not math.isfinite(item) for item in values):
        raise ValueError("向量包含 NaN 或无穷大")
    return values


def l2_normalize(vector: Iterable[float], *, dimension: int) -> list[float]:
    """对向量做 L2 归一化，适合 COSINE / IP 检索前保持分数稳定。"""
    values = ensure_vector(vector, dimension=dimension)
    norm = math.sqrt(sum(item * item for item in values))
    if norm == 0:
        raise ValueError("零向量不能归一化")
    return [item / norm for item in values]


def build_demo_chunks(*, dimension: int = 8) -> list[Document]:
    """构造稳定的 LangChain Document，避免示例依赖外部 embedding 服务。"""
    rows = [
        (
            "doc-python-1",
            "Python 的上下文管理器用于可靠释放资源",
            "python-guide",
            1,
            [0.92, 0.11, 0.08, 0.03, 0.02, 0.01, 0.0, 0.0],
        ),
        (
            "doc-python-2",
            "asyncio 适合处理大量 I/O 等待任务",
            "python-guide",
            2,
            [0.84, 0.22, 0.14, 0.06, 0.03, 0.02, 0.0, 0.0],
        ),
        (
            "doc-milvus-1",
            "Milvus 使用 collection、schema 和 index 组织向量数据",
            "milvus-guide",
            1,
            [0.05, 0.08, 0.91, 0.13, 0.08, 0.04, 0.02, 0.0],
        ),
        (
            "doc-milvus-2",
            "向量检索常配合 scalar filter 限定文档来源",
            "milvus-guide",
            2,
            [0.04, 0.05, 0.88, 0.20, 0.10, 0.05, 0.03, 0.0],
        ),
    ]
    return [
        Document(
            id=row_id,
            page_content=text,
            metadata={
                "source": source,
                "chunk_no": chunk_no,
                "vector": l2_normalize(vector, dimension=dimension),
            },
        )
        for row_id, text, source, chunk_no, vector in rows
    ]


def to_milvus_rows(documents: Iterable[Document], *, dimension: int) -> list[dict[str, object]]:
    """把 LangChain Document 转换为 Milvus insert/upsert 接收的行数据。"""
    rows: list[dict[str, object]] = []
    for document in documents:
        if not document.id:
            raise ValueError("Document.id 不能为空，Milvus 需要稳定主键")

        metadata = document.metadata
        try:
            source = metadata["source"]
            chunk_no = metadata["chunk_no"]
            vector = metadata["vector"]
        except KeyError as exc:
            raise ValueError(f"Document.metadata 缺少必需字段: {exc.args[0]}") from exc

        rows.append(
            {
                "id": document.id,
                "text": document.page_content,
                "source": str(source),
                "chunk_no": int(chunk_no),
                "vector": ensure_vector(cast(Iterable[float], vector), dimension=dimension),
            }
        )
    return rows


def _demo() -> None:
    chunks = build_demo_chunks()
    query = l2_normalize([0.05, 0.08, 0.90, 0.14, 0.08, 0.04, 0.02, 0.0], dimension=8)
    rows = to_milvus_rows(chunks, dimension=8)
    print(f"chunks={len(chunks)}")
    print(f"query_dim={len(query)}")
    print(f"first_row_keys={sorted(rows[0].keys())}")


if __name__ == "__main__":
    _demo()
