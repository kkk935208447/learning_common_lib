"""
目标: 演示用 LangChain Document 表达写入 Milvus 前的向量数据协议
关键 API: Document, ensure_vector, l2_normalize, to_milvus_rows
本例重点参数:
- Document(id, page_content, metadata): id 映射 Milvus 主键，page_content 映射 text，metadata 承载 source、chunk_no、vector。
- ensure_vector(vector, dimension): 写入前校验 embedding 维度和非法数值。
- to_milvus_rows(...): 把文档协议转换为 Milvus row dict，字段必须和后续 schema 对齐。
流程索引: roadmap.md#milvus-工程使用流程
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/01_basics/01_vector_protocol.py
预期现象: 打印文档块数量、Milvus 行字段、归一化后的向量长度
生产提醒: embedding 维度必须在写入前校验，不能等 Milvus 报错后再排查
"""

import math
from collections.abc import Iterable
from typing import cast

from langchain_core.documents import Document


def ensure_vector(vector: Iterable[float], *, dimension: int) -> list[float]:
    values = [float(item) for item in vector]
    if len(values) != dimension:
        raise ValueError(f"向量维度不匹配: expected={dimension}, actual={len(values)}")
    if any(not math.isfinite(item) for item in values):
        raise ValueError("向量包含 NaN 或无穷大")
    return values


def l2_normalize(vector: Iterable[float], *, dimension: int) -> list[float]:
    values = ensure_vector(vector, dimension=dimension)
    norm = math.sqrt(sum(item * item for item in values))
    if norm == 0:
        raise ValueError("零向量不能归一化")
    return [item / norm for item in values]


def build_demo_chunks(*, dimension: int) -> list[Document]:
    return [
        Document(
            id="doc-milvus-1",
            page_content="Milvus 使用 collection、schema 和 index 组织向量数据",
            metadata={
                "source": "milvus-guide",
                "chunk_no": 1,
                "vector": l2_normalize(
                    [0.05, 0.08, 0.91, 0.13, 0.08, 0.04, 0.02, 0.0],
                    dimension=dimension,
                ),
            },
        ),
        Document(
            id="doc-python-1",
            page_content="Python 的上下文管理器用于可靠释放资源",
            metadata={
                "source": "python-guide",
                "chunk_no": 1,
                "vector": l2_normalize(
                    [0.92, 0.11, 0.08, 0.03, 0.02, 0.01, 0.0, 0.0],
                    dimension=dimension,
                ),
            },
        ),
    ]


def to_milvus_rows(documents: Iterable[Document], *, dimension: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for document in documents:
        if not document.id:
            raise ValueError("Document.id 不能为空，Milvus 需要稳定主键")
        metadata = document.metadata
        rows.append(
            {
                "id": document.id,
                "text": document.page_content,
                "source": str(metadata["source"]),
                "chunk_no": int(metadata["chunk_no"]),
                "vector": ensure_vector(cast(Iterable[float], metadata["vector"]), dimension=dimension),
            }
        )
    return rows


def main() -> None:
    dimension = 8
    chunks = build_demo_chunks(dimension=dimension)
    rows = to_milvus_rows(chunks, dimension=dimension)
    query_vector = l2_normalize(
        [0.05, 0.08, 0.90, 0.14, 0.08, 0.04, 0.02, 0.0],
        dimension=dimension,
    )

    print(f"chunk_count={len(chunks)}")
    print(f"first_chunk_id={chunks[0].id}")
    print(f"milvus_row_keys={sorted(rows[0].keys())}")
    print(f"query_dimension={len(query_vector)}")
    print(f"query_norm={sum(item * item for item in query_vector):.4f}")


if __name__ == "__main__":
    main()
