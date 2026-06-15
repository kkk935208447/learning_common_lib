# 可复用模板说明

本目录提供从教程示例提炼出的生产级骨架，迁移到真实项目时可直接复用或裁剪。模板不是基础示例的前置依赖，示例都能独立运行。

## 模块清单

| 模块 | 职责 | 关键对象 |
|------|------|----------|
| `settings.py` | 集中管理连接配置和索引命名规则 | `ElasticsearchSettings`、`load_settings`、`ensure_local_no_proxy` |
| `client_factory.py` | 创建同步/异步客户端，注入超时、重试、认证 | `create_client`、`create_async_client` |
| `sync_repository.py` | 单索引同步仓储：建索引、写入、检索、遍历、删除 | `SyncElasticsearchRepository` |
| `async_repository.py` | 单索引异步仓储，适配 FastAPI/worker | `AsyncElasticsearchRepository` |

## 设计取舍

- **配置与连接分离**：`settings.py` 只负责读配置，不主动连接 ES；连通性由调用层暴露。
- **客户端复用**：`client_factory` 产出的客户端应在应用生命周期内复用，不要每请求新建。
- **异常透传**：仓储不吞异常，`NotFoundError`/`ConflictError` 等向上层透传，由调用方决定重试或映射状态码。
- **可预期缺失返回 None**：`get_document` 对 404 返回 `None` 而非抛异常，区别于不可预期错误。
- **索引命名受控**：`index_name(topic)` 统一加前缀并校验合法性，避免误操作真实索引。

## 模板暴露的常用客户端参数

| 参数/环境变量 | 作用 | 说明 |
|---------------|------|------|
| `ES_HOST` | Elasticsearch 地址 | 本地默认 `http://localhost:9200`；生产可扩展为多 hosts 配置 |
| `ES_API_KEY` | API Key 认证 | 适合 Elastic Cloud 或服务间调用；本地教学可留空 |
| `ES_USERNAME` / `ES_PASSWORD` | 用户名密码认证 | Py 客户端对应 `basic_auth=(user, password)`；未设置 API Key 时启用 |
| `ES_REQUEST_TIMEOUT` | 单次请求超时 | 默认 10 秒；bulk/reindex 这类重操作可用 `client.options(request_timeout=...)` 覆盖 |
| `retry_on_timeout` / `max_retries` | 超时重试 | 模板内置，适合幂等或可安全重试的请求 |
| `retry_on_status` | 状态码重试 | 模板覆盖 408/429/502/503/504，不对 400/404 这类请求错误重试 |
| `http_compress` | HTTP 压缩 | 模板默认开启，降低网络传输 |

生产中还常见 `verify_certs`、`ca_certs`。本模板保留 API Key/basic_auth 两种认证入口；如果接入自签 CA，应在项目配置层统一扩展证书路径。

## 运行方式

作为模块运行（推荐，IDE 可点击进入源码）：

```bash
cd /home/shayuer/document/learning_some/learning_common_lib
UV_CACHE_DIR=/tmp/uv-cache uv run python -m learning_common_lib.python基础.elasticsearch教程.templates.settings
UV_CACHE_DIR=/tmp/uv-cache uv run python -m learning_common_lib.python基础.elasticsearch教程.templates.client_factory
UV_CACHE_DIR=/tmp/uv-cache uv run python -m learning_common_lib.python基础.elasticsearch教程.templates.sync_repository
UV_CACHE_DIR=/tmp/uv-cache uv run python -m learning_common_lib.python基础.elasticsearch教程.templates.async_repository
```

直接运行单个文件（模板内置受控回退路径，便于快速试跑）：

```bash
cd src/learning_common_lib/python基础/elasticsearch教程
UV_CACHE_DIR=/tmp/uv-cache uv run python templates/sync_repository.py
```

每个模块的 `_demo()` 都会创建教学专用索引、跑一遍核心方法、再清理，运行后能直接观察输出。

## 在真实项目中使用

```python
from learning_common_lib.python基础.elasticsearch教程.templates import (
    load_settings,
    create_client,
    SyncElasticsearchRepository,
)

settings = load_settings()
client = create_client(settings)
repo = SyncElasticsearchRepository(client, settings.index_name("articles"))

repo.ensure_index(mappings={"properties": {"title": {"type": "text"}}})
repo.index_document("a1", {"title": "hello elasticsearch"}, refresh=True)
hits = repo.search({"match": {"title": "elasticsearch"}})
client.close()
```

生产环境替换点：
- `settings.host` 改为多节点列表，注入 `api_key` 和 TLS。
- 客户端做成应用单例，启动时建、关闭时释放。
- mapping 抽到版本化文件或 index template，不写死在代码里。
