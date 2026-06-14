"""Milvus 教程可复用模板包。

包级导出使用延迟加载，避免 `python -m` 运行子模块时提前导入其他模板。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AsyncMilvusRepository": ".async_repository",
    "Document": ".vector_utils",
    "FLOAT_VECTOR_INDEXES": ".index_catalog",
    "IndexProfile": ".index_catalog",
    "MilvusSettings": ".settings",
    "SPARSE_VECTOR_INDEXES": ".index_catalog",
    "SyncMilvusRepository": ".sync_repository",
    "build_demo_chunks": ".vector_utils",
    "ensure_vector": ".vector_utils",
    "get_index_profile": ".index_catalog",
    "l2_normalize": ".vector_utils",
    "load_settings": ".settings",
    "to_milvus_rows": ".vector_utils",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """按需加载模板对象，保留包级导入的便利性。"""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
