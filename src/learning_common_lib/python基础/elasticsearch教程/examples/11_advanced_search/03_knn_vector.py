"""
目标: 用 dense_vector + kNN 做向量语义检索，并和关键词检索组合成混合召回
关键 API: dense_vector(dims/index/similarity), search(knn), knn + query 混合
本例重点参数:
- dense_vector.dims: 必须等于 embedding 模型输出维度，写错会导致写入失败。
- dense_vector.similarity: cosine/dot_product/l2_norm 要与向量归一化方式匹配。
- knn.k/num_candidates/boost: k 是最终近邻数，num_candidates 越大召回越高但越慢，boost 调混合权重。
Python 版本: 3.11+
运行命令: uv run python examples/11_advanced_search/03_knn_vector.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200
预期现象: kNN 按向量相似度召回，混合检索同时考虑关键词匹配和向量相似度
生产提醒: 真实向量来自 embedding 模型；dims 必须和模型输出一致，similarity 要和归一化方式匹配
"""

import math
import os

from elasticsearch import Elasticsearch, helpers


ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
INDEX_NAME = os.getenv("ES_INDEX", "learning_es_knn")
# 教学用低维向量；真实场景 dims 由 embedding 模型决定（如 384/768/1536）
DIMENSION = int(os.getenv("ES_DIMENSION", "4"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def l2_normalize(vector: list[float]) -> list[float]:
    """cosine similarity 下建议归一化向量。"""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise ValueError("零向量不能归一化")
    return [x / norm for x in vector]


def seed(client: Elasticsearch, index_name: str, dimension: int) -> None:
    client.options(ignore_status=404).indices.delete(index=index_name)
    client.indices.create(
        index=index_name,
        mappings={
            "properties": {
                "title": {"type": "text"},
                # dense_vector + index=True 才能做 kNN；similarity 决定打分方式
                "embedding": {
                    "type": "dense_vector",
                    "dims": dimension,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        },
    )
    docs = [
        {"title": "Elasticsearch 向量检索", "embedding": l2_normalize([0.9, 0.1, 0.0, 0.0])},
        {"title": "Python 异步编程", "embedding": l2_normalize([0.0, 0.0, 0.9, 0.1])},
        {"title": "Elasticsearch 聚合分析", "embedding": l2_normalize([0.8, 0.2, 0.1, 0.0])},
    ]
    actions = [{"_index": index_name, "_id": str(i), "_source": d} for i, d in enumerate(docs)]
    helpers.bulk(client, actions, refresh="wait_for")


def main() -> None:
    ensure_local_no_proxy()
    client = Elasticsearch(ES_HOST, request_timeout=10)
    try:
        seed(client, INDEX_NAME, DIMENSION)

        # 查询向量（真实场景由同一个 embedding 模型对 query 编码得到）
        query_vector = l2_normalize([0.85, 0.15, 0.0, 0.0])

        # 纯 kNN：k 是返回数，num_candidates 是每个分片的候选数（越大越准越慢）
        knn_only = client.search(
            index=INDEX_NAME,
            knn={"field": "embedding", "query_vector": query_vector, "k": 2, "num_candidates": 10},
            source=["title"],
        )
        print("纯向量 kNN 召回:")
        for hit in knn_only["hits"]["hits"]:
            print(f"  id={hit['_id']} score={hit['_score']:.4f} title={hit['_source']['title']}")

        # 混合检索：knn 和 query 同时给出，ES 会合并两者得分
        hybrid = client.search(
            index=INDEX_NAME,
            query={"match": {"title": "聚合"}},
            knn={"field": "embedding", "query_vector": query_vector, "k": 2, "num_candidates": 10, "boost": 0.5},
            source=["title"],
            size=3,
        )
        print("关键词 + 向量混合召回:")
        for hit in hybrid["hits"]["hits"]:
            print(f"  id={hit['_id']} score={hit['_score']:.4f} title={hit['_source']['title']}")
    finally:
        client.options(ignore_status=404).indices.delete(index=INDEX_NAME)
        client.close()


if __name__ == "__main__":
    main()
