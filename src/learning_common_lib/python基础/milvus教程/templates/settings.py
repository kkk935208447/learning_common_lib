"""
解决什么问题: 集中管理 Milvus 教程的连接参数、集合命名和运行模式
输入输出约定: 从环境变量读取配置，返回不可变 Settings 对象
失败策略: 不在配置层主动连接 Milvus，连接失败由调用层显式处理
适用边界: 教程和小型服务骨架；生产环境应接入项目统一配置系统
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DIMENSION = 8
DEFAULT_COLLECTION_PREFIX = "learning_milvus"
DEFAULT_LITE_PATH = ".milvus_tutorial/milvus_lite.db"
LOCAL_NO_PROXY = "127.0.0.1,localhost"

COLLECTION_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


@dataclass(frozen=True)
class MilvusSettings:
    """Milvus 教程运行配置。"""

    uri: str
    token: str
    collection_prefix: str
    dimension: int
    timeout: float

    def collection_name(self, topic: str) -> str:
        """生成教程专用集合名，避免误删用户真实集合。"""
        normalized = re.sub(r"[^A-Za-z0-9_]", "_", topic.strip())
        normalized = re.sub(r"_+", "_", normalized).strip("_").lower()
        if not normalized:
            raise ValueError("集合主题不能为空")
        name = f"{self.collection_prefix}_{normalized}"
        if not COLLECTION_NAME_RE.match(name):
            raise ValueError(f"非法集合名: {name}")
        return name

    @property
    def using_lite(self) -> bool:
        """判断当前 URI 是否是 Milvus Lite 本地文件路径。"""
        return self.uri.endswith(".db") or self.uri.endswith(".db/")


def load_settings() -> MilvusSettings:
    """从环境变量加载配置。

    支持的环境变量：
    - MILVUS_URI：默认使用教程目录下的 Milvus Lite 文件
    - MILVUS_TOKEN：云服务或开启认证的 Standalone 使用；本地默认 Standalone 通常留空。
      PyMilvus 也支持 user/password 分开传入，适合更完整的项目配置层。
    - MILVUS_COLLECTION_PREFIX：教程专用集合名前缀
    - MILVUS_DIMENSION：示例向量维度
    - MILVUS_TIMEOUT：单次 Milvus 操作超时时间
    """
    uri = os.getenv("MILVUS_URI", DEFAULT_LITE_PATH)
    token = os.getenv("MILVUS_TOKEN", "")
    collection_prefix = os.getenv("MILVUS_COLLECTION_PREFIX", DEFAULT_COLLECTION_PREFIX)
    dimension = int(os.getenv("MILVUS_DIMENSION", str(DEFAULT_DIMENSION)))
    timeout = float(os.getenv("MILVUS_TIMEOUT", "8"))

    if uri.endswith(".db"):
        ensure_local_no_proxy()
        Path(uri).parent.mkdir(parents=True, exist_ok=True)

    return MilvusSettings(
        uri=uri,
        token=token,
        collection_prefix=collection_prefix,
        dimension=dimension,
        timeout=timeout,
    )


def ensure_local_no_proxy() -> None:
    """确保 Milvus Lite 的本机 gRPC 连接不会经过 HTTP 代理。"""
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def _demo() -> None:
    settings = load_settings()
    print(f"uri={settings.uri}")
    print(f"using_lite={settings.using_lite}")
    print(f"collection={settings.collection_name('quickstart')}")
    print(f"dimension={settings.dimension}")


if __name__ == "__main__":
    _demo()
