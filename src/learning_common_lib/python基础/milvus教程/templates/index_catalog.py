"""
解决什么问题: 汇总 Milvus 常见索引类型、构建参数和搜索参数建议
输入输出约定: 返回纯 Python 数据结构，便于文档、示例和配置系统复用
失败策略: 不连接 Milvus，只做参数目录和推荐说明
适用边界: 教程、配置评审、索引选型讨论；生产压测仍以真实数据和查询分布为准
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IndexProfile:
    """一个 Milvus 索引类型的参数说明。"""

    index_type: str
    metrics: tuple[str, ...]
    build_params: dict[str, Any]
    search_params: dict[str, Any]
    use_case: str
    caution: str


FLOAT_VECTOR_INDEXES: tuple[IndexProfile, ...] = (
    IndexProfile(
        index_type="AUTOINDEX",
        metrics=("COSINE", "L2", "IP"),
        build_params={},
        search_params={"metric_type": "COSINE"},
        use_case="优先用于入门、本地开发、云端自动调优和缺少压测数据的阶段。",
        caution="自动索引不等于免压测；生产仍要观察召回率、延迟和资源成本。",
    ),
    IndexProfile(
        index_type="FLAT",
        metrics=("COSINE", "L2", "IP"),
        build_params={},
        search_params={"metric_type": "L2"},
        use_case="小数据集、强召回基线、索引调优前的正确性对照。",
        caution="全量扫描，数据量变大后延迟和 CPU 成本会快速上升。",
    ),
    IndexProfile(
        index_type="IVF_FLAT",
        metrics=("COSINE", "L2", "IP"),
        build_params={"nlist": 128},
        search_params={"metric_type": "COSINE", "params": {"nprobe": 16}},
        use_case="中等规模数据，想用 nlist/nprobe 明确控制召回和延迟。",
        caution="nprobe 越大召回越高但越慢；nlist 需要结合数据量和分布压测。",
    ),
    IndexProfile(
        index_type="IVF_SQ8",
        metrics=("COSINE", "L2", "IP"),
        build_params={"nlist": 128},
        search_params={"metric_type": "COSINE", "params": {"nprobe": 16}},
        use_case="希望减少内存占用，同时接受量化带来的召回损失。",
        caution="量化会降低精度，必须用业务评测集比较召回。",
    ),
    IndexProfile(
        index_type="IVF_PQ",
        metrics=("COSINE", "L2", "IP"),
        build_params={"nlist": 128, "m": 8, "nbits": 8},
        search_params={"metric_type": "COSINE", "params": {"nprobe": 16}},
        use_case="大规模向量、内存敏感、可接受更明显压缩误差的场景。",
        caution="m 需要能整除向量维度；压缩参数不合适会明显损伤召回。",
    ),
    IndexProfile(
        index_type="HNSW",
        metrics=("COSINE", "L2", "IP"),
        build_params={"M": 16, "efConstruction": 200},
        search_params={"metric_type": "COSINE", "params": {"ef": 64}},
        use_case="低延迟、高召回的在线检索，常用于中高 QPS 服务。",
        caution="M 和 efConstruction 越大构建越慢、内存越高；ef 越大查询越慢。",
    ),
    IndexProfile(
        index_type="DISKANN",
        metrics=("COSINE", "L2", "IP"),
        build_params={},
        search_params={"metric_type": "COSINE", "params": {"search_list": 100}},
        use_case="超大规模、内存放不下全部向量、需要磁盘型 ANN 的场景。",
        caution="依赖部署形态和版本能力，必须用真实硬件压测。",
    ),
    IndexProfile(
        index_type="SCANN",
        metrics=("COSINE", "L2", "IP"),
        build_params={"nlist": 128, "with_raw_data": True},
        search_params={"metric_type": "COSINE", "params": {"nprobe": 16, "reorder_k": 100}},
        use_case="需要候选召回后重新排序的高召回场景。",
        caution="参数较多，必须明确召回、重排和延迟目标后再使用。",
    ),
)

SPARSE_VECTOR_INDEXES: tuple[IndexProfile, ...] = (
    IndexProfile(
        index_type="SPARSE_INVERTED_INDEX",
        metrics=("IP", "BM25"),
        build_params={"inverted_index_algo": "DAAT_MAXSCORE"},
        search_params={"metric_type": "BM25"},
        use_case="稀疏向量、BM25 全文检索、dense+sparse 混合检索。",
        caution="BM25 需要在 schema 中配置 analyzer 和 Function，不能事后随意补。",
    ),
)


def get_index_profile(index_type: str) -> IndexProfile:
    """按索引名查找参数说明。"""
    normalized = index_type.upper()
    for profile in (*FLOAT_VECTOR_INDEXES, *SPARSE_VECTOR_INDEXES):
        if profile.index_type == normalized:
            return profile
    raise ValueError(f"未收录的索引类型: {index_type}")


def build_index_param(profile: IndexProfile, *, field_name: str = "vector") -> dict[str, Any]:
    """生成可传给 add_index 的关键参数字典。"""
    metric_type = profile.metrics[0] if profile.index_type == "FLAT" else profile.search_params["metric_type"]
    return {
        "field_name": field_name,
        "index_type": profile.index_type,
        "metric_type": metric_type,
        "params": profile.build_params,
    }


def _demo() -> None:
    for name in ("AUTOINDEX", "IVF_FLAT", "HNSW", "SPARSE_INVERTED_INDEX"):
        profile = get_index_profile(name)
        index_param = build_index_param(profile)
        print(f"{profile.index_type}: metrics={profile.metrics} build={index_param['params']}")


if __name__ == "__main__":
    _demo()
