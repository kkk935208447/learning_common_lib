"""
解决什么问题: 集中管理 Elasticsearch 教程的连接参数和索引命名，避免散落在各处
输入输出约定: 从环境变量读取配置，返回不可变 Settings 对象
失败策略: 不在配置层主动连接 ES，连接失败由调用层显式处理
适用边界: 教程和小型服务骨架；生产环境应接入项目统一配置系统并启用 TLS + API Key 或用户名密码认证
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


DEFAULT_HOST = "http://localhost:9200"
DEFAULT_INDEX_PREFIX = "learning_es"
DEFAULT_TIMEOUT = 10.0
LOCAL_NO_PROXY = "127.0.0.1,localhost"

# ES 索引名规则：小写、不能以 _/-/+ 开头、不含大写和特殊字符
INDEX_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_\-.]{0,254}$")


@dataclass(frozen=True)
class ElasticsearchSettings:
    """Elasticsearch 教程运行配置。"""

    host: str
    api_key: str
    username: str
    password: str
    index_prefix: str
    timeout: float

    def index_name(self, topic: str) -> str:
        """生成教程专用索引名，统一加前缀，避免误删用户真实索引。"""
        normalized = re.sub(r"[^a-z0-9_\-.]", "_", topic.strip().lower())
        normalized = normalized.strip("_-.")
        candidate = f"{self.index_prefix}_{normalized}" if normalized else self.index_prefix
        if not INDEX_NAME_RE.match(candidate):
            raise ValueError(f"非法索引名: {candidate}")
        return candidate


def load_settings() -> ElasticsearchSettings:
    """从环境变量加载配置，所有项都有教学默认值。"""
    return ElasticsearchSettings(
        host=os.getenv("ES_HOST", DEFAULT_HOST),
        api_key=os.getenv("ES_API_KEY", ""),
        username=os.getenv("ES_USERNAME", ""),
        password=os.getenv("ES_PASSWORD", ""),
        index_prefix=os.getenv("ES_INDEX_PREFIX", DEFAULT_INDEX_PREFIX),
        timeout=float(os.getenv("ES_REQUEST_TIMEOUT", str(DEFAULT_TIMEOUT))),
    )


def ensure_local_no_proxy() -> None:
    """确保本机连接不会经过 HTTP 代理。"""
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def _demo() -> None:
    settings = load_settings()
    print(f"host={settings.host}")
    auth_mode = "api_key" if settings.api_key else "basic_auth" if settings.username and settings.password else "none"
    print(f"auth_mode={auth_mode}")
    print(f"index_prefix={settings.index_prefix}")
    print(f"timeout={settings.timeout}")
    print(f"index_name('articles')={settings.index_name('Articles')}")


if __name__ == "__main__":
    _demo()
