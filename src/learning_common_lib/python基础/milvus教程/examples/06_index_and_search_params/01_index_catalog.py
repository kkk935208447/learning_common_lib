"""
目标: 系统展示 Milvus 常见索引类型、构建参数和搜索参数
关键 API: prepare_index_params, add_index, index_type, metric_type, params
Python 版本: 3.11+
运行命令: UV_CACHE_DIR=/tmp/uv-cache uv run python examples/06_index_and_search_params/01_index_catalog.py
预期现象: 打印 AUTOINDEX、FLAT、IVF_FLAT、IVF_PQ、HNSW、DISKANN、SCANN、SPARSE_INVERTED_INDEX 的参数表
生产提醒: 索引参数必须用真实数据压测，不能只按示例值上线
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IndexProfile:
    index_type: str
    metric_type: str
    build_params: dict[str, Any]
    search_params: dict[str, Any]
    use_case: str


INDEX_PROFILES = [
    IndexProfile("AUTOINDEX", "COSINE", {}, {"metric_type": "COSINE"}, "入门、云端自动调优、缺少压测数据时的默认选择"),
    IndexProfile("FLAT", "L2", {}, {"metric_type": "L2"}, "小数据集和召回正确性基线"),
    IndexProfile("IVF_FLAT", "COSINE", {"nlist": 128}, {"metric_type": "COSINE", "params": {"nprobe": 16}}, "中等规模，显式控制召回/延迟"),
    IndexProfile("IVF_SQ8", "COSINE", {"nlist": 128}, {"metric_type": "COSINE", "params": {"nprobe": 16}}, "希望降低内存占用，可接受量化误差"),
    IndexProfile("IVF_PQ", "COSINE", {"nlist": 128, "m": 8, "nbits": 8}, {"metric_type": "COSINE", "params": {"nprobe": 16}}, "大规模压缩存储，召回需要重点验证"),
    IndexProfile("HNSW", "COSINE", {"M": 16, "efConstruction": 200}, {"metric_type": "COSINE", "params": {"ef": 64}}, "低延迟高召回在线检索"),
    IndexProfile("DISKANN", "COSINE", {}, {"metric_type": "COSINE", "params": {"search_list": 100}}, "超大规模磁盘型 ANN"),
    IndexProfile("SCANN", "COSINE", {"nlist": 128, "with_raw_data": True}, {"metric_type": "COSINE", "params": {"nprobe": 16, "reorder_k": 100}}, "候选召回后重排"),
    IndexProfile("SPARSE_INVERTED_INDEX", "BM25", {"inverted_index_algo": "DAAT_MAXSCORE"}, {"metric_type": "BM25"}, "稀疏向量、全文检索、混合检索"),
]


def main() -> None:
    for profile in INDEX_PROFILES:
        print(f"{profile.index_type}")
        print(f"  metric_type={profile.metric_type}")
        print(f"  build_params={profile.build_params}")
        print(f"  search_params={profile.search_params}")
        print(f"  use_case={profile.use_case}")


if __name__ == "__main__":
    main()
