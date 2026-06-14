"""Elasticsearch 教程可复用模板包。

包级导出使用延迟加载，避免 `python -m` 运行子模块时提前导入其他模板。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AsyncElasticsearchRepository": ".async_repository",
    "ElasticsearchSettings": ".settings",
    "SyncElasticsearchRepository": ".sync_repository",
    "create_async_client": ".client_factory",
    "create_client": ".client_factory",
    "ensure_local_no_proxy": ".settings",
    "load_settings": ".settings",
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
