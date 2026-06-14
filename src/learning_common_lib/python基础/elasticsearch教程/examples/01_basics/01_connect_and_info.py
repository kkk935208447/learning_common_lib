"""
目标: 跑通 Elasticsearch 连接闭环，确认客户端版本与服务端版本兼容
关键 API: Elasticsearch, ping, info, cluster.health
Python 版本: 3.11+
运行命令: uv run python examples/01_basics/01_connect_and_info.py
环境准备: 本地 Elasticsearch 8.x 运行在 http://localhost:9200，无需账号密码
预期现象: 打印 ping 结果、服务端版本号和集群健康状态
生产提醒: 客户端大版本必须与服务端大版本一致；本地无认证仅适合教学，生产必须开启 TLS 和 API Key
"""

import os

import elasticsearch
from elasticsearch import Elasticsearch


# 教程统一在文件顶部定义可调参数；下方函数通过透传参数使用，不直接读全局
ES_HOST = os.getenv("ES_HOST", "http://localhost:9200")
REQUEST_TIMEOUT = float(os.getenv("ES_REQUEST_TIMEOUT", "10"))
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def ensure_local_no_proxy() -> None:
    """本机连接必须绕过 HTTP 代理，否则代理会拦截 localhost 请求。"""
    for key in ("NO_PROXY", "no_proxy"):
        values = [item.strip() for item in os.getenv(key, "").split(",") if item.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in values:
                values.append(item)
        os.environ[key] = ",".join(values)


def connect_client(host: str, timeout: float) -> Elasticsearch:
    """创建同步客户端。request_timeout 控制单次 HTTP 请求超时。"""
    return Elasticsearch(host, request_timeout=timeout)


def report_cluster(client: Elasticsearch, host: str) -> None:
    """打印连接、版本和集群健康信息。"""
    # ping 只返回 True/False，不会抛出连接异常，适合健康探针
    reachable = client.ping()
    print(f"host={host}")
    print(f"ping={reachable}")
    if not reachable:
        print("无法连接 Elasticsearch，请确认本地服务已启动")
        return

    info = client.info()
    print(f"server_version={info['version']['number']}")
    # 客户端大版本必须与服务端大版本一致，否则会被服务端拒绝
    print(f"client_major={elasticsearch.__version__[0]}")

    # 集群健康：green=全部分片可用，yellow=主分片可用副本未分配，red=有主分片不可用
    health = client.cluster.health()
    print(f"cluster_status={health['status']}")
    print(f"number_of_nodes={health['number_of_nodes']}")


def main() -> None:
    ensure_local_no_proxy()
    client = connect_client(ES_HOST, REQUEST_TIMEOUT)
    try:
        report_cluster(client, ES_HOST)
    finally:
        # 客户端持有连接池，使用完必须关闭
        client.close()


if __name__ == "__main__":
    main()
