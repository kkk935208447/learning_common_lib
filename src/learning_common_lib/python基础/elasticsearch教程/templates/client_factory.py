"""
解决什么问题: 统一创建同步/异步 Elasticsearch 客户端，注入超时、重试和认证
输入输出约定: 输入 Settings，输出 Elasticsearch 或 AsyncElasticsearch 实例
失败策略: 创建时不校验连通性；连通性由调用层 ping 或首个请求暴露
适用边界: 教程和服务骨架；生产应从配置中心注入 hosts、API Key/basic_auth 和 TLS 证书
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from elasticsearch import AsyncElasticsearch, Elasticsearch

try:
    from .settings import ElasticsearchSettings, ensure_local_no_proxy, load_settings
except ImportError:
    # 支持直接运行单个模板文件：回退到顶层包路径
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.settings import (  # type: ignore[no-redef]
        ElasticsearchSettings,
        ensure_local_no_proxy,
        load_settings,
    )


def _common_kwargs(settings: ElasticsearchSettings) -> dict[str, Any]:
    """同步和异步客户端共享的构造参数。"""
    kwargs: dict[str, Any] = {
        "hosts": settings.host,
        "request_timeout": settings.timeout,
        # 瞬时网络错误自动重试，配合幂等写入更安全
        "retry_on_timeout": True,
        "max_retries": 3,
        # 对这些可恢复状态码自动重试：408 超时、429 限流、502/503/504 网关/不可用
        "retry_on_status": (408, 429, 502, 503, 504),
        # gzip 压缩请求和响应体，降低大批量/大结果集的网络开销
        "http_compress": True,
    }
    # 生产优先用 API Key；用户名密码环境用 basic_auth；本地教学默认无认证。
    if settings.api_key:
        kwargs["api_key"] = settings.api_key
    elif settings.username and settings.password:
        kwargs["basic_auth"] = (settings.username, settings.password)
    return kwargs


def create_client(settings: ElasticsearchSettings | None = None) -> Elasticsearch:
    """创建同步客户端。"""
    ensure_local_no_proxy()
    settings = settings or load_settings()
    return Elasticsearch(**_common_kwargs(settings))


def create_async_client(settings: ElasticsearchSettings | None = None) -> AsyncElasticsearch:
    """创建异步客户端，配合 async with 或显式 await close() 管理生命周期。"""
    ensure_local_no_proxy()
    settings = settings or load_settings()
    return AsyncElasticsearch(**_common_kwargs(settings))


def _demo() -> None:
    client = create_client()
    try:
        print(f"ping={client.ping()}")
    finally:
        client.close()


if __name__ == "__main__":
    _demo()
