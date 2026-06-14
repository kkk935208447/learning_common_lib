# Elasticsearch 教程（连接 + 检索 + 聚合 + 生产实践）

本教程教你用 Python 官方客户端 `elasticsearch` 跑通从连接、mapping、CRUD、批量写入、Query DSL、聚合、分页到错误恢复、索引切换、异步客户端和高级 DSL 的完整检索链路。

这份教程放在 `src/learning_common_lib/python基础/` 下，面向已经掌握 Python 基础、准备学习全文检索和 Elasticsearch 的开发者。建议先读本文完成环境准备和快速开始，再按 [roadmap.md](roadmap.md) 的顺序逐个运行示例；遇到工程取舍时看 [architecture_map.md](architecture_map.md) 和 [best_practices.md](best_practices.md)，排查问题时看 [pitfalls.md](pitfalls.md)。

教程采用“先连接、后建模、再检索、最后生产化”的路线。前几节用同步 `Elasticsearch` 客户端建立 index、mapping、document、search、aggregation 的完整心智模型；基础稳定后，再进入 bulk 批量、深度分页、乐观并发、alias 蓝绿切换、`AsyncElasticsearch` 异步客户端和 `elasticsearch.dsl` 面向对象 API 等进阶主题。

## 适合人群

- 想从零跑通 Elasticsearch 全文检索闭环的 Python 开发者。
- 正在做搜索、日志分析、RAG 关键词召回或数据聚合的工程师。
- 已经学过本仓库 `asyncio教程`，希望把异步客户端接入服务端的同学。
- 想理解 Elasticsearch index、mapping、analyzer、query、aggregation、pagination 生命周期，而不是只调用封装库的同学。

## 环境要求

| 项目 | 要求 | 说明 |
|------|------|------|
| Python | `>=3.11,<3.12` | 与当前仓库一致 |
| 依赖 | `elasticsearch[async]>=8.19,<9` | 已写入 `pyproject.toml`，**客户端大版本必须与服务端一致** |
| ES 服务 | Elasticsearch 8.x（本教程在 8.19.14 上验证） | 本地默认 `http://localhost:9200`，无认证 |
| 缓存目录 | 建议 `UV_CACHE_DIR=/tmp/uv-cache` | 避免受限环境写用户全局缓存 |

> **版本对齐很关键**：Elasticsearch 客户端会在请求头里声明 `compatible-with=<major>`，服务端只接受同大版本。9.x 客户端连 8.x 服务端会直接报 `media_type_header_exception`。本教程把客户端固定在 `>=8.19,<9` 以匹配 8.x 服务端。

安装依赖：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync
```

确认本地 ES 已启动：

```bash
curl http://localhost:9200
```

应返回包含 `"version": {"number": "8.x.x"}` 的 JSON。如果你用 Docker 起 ES（教学场景，关闭安全认证）：

```bash
docker run -d --name elasticsearch -p 9200:9200 \
  -e "discovery.type=single-node" \
  -e "xpack.security.enabled=false" \
  -e "ES_JAVA_OPTS=-Xms1g -Xmx1g" \
  docker.elastic.co/elasticsearch/elasticsearch:8.19.14
```

> 如果你的环境设置了 HTTP/HTTPS 代理，请确保 `NO_PROXY` 和 `no_proxy` 包含 `127.0.0.1,localhost`；教程示例和 smoke 已自动补齐这两个变量。生产环境必须开启 TLS 和 API Key，本教程的无认证连接仅适合本地学习。

## 示例独立性约定

`examples/` 下的每个 `.py` 文件都自包含：自己重建索引、写入教学数据、运行、清理。即使多个示例重复了连接配置或 seed 代码，也优先让读者打开单个文件就能直接理解和运行。所有教学索引统一使用 `learning_es_` 前缀，清理只作用于示例自己创建的索引，不会影响你已有的数据。

本目录的 `templates/` 是迁移到真实项目时可复用的骨架，不是基础示例的隐式前置依赖。模板优先使用包内相对导入，同时保留直接运行单个模板文件时的受控回退路径：

```bash
cd /home/shayuer/document/learning_some/learning_common_lib
UV_CACHE_DIR=/tmp/uv-cache uv run python -m learning_common_lib.python基础.elasticsearch教程.templates.sync_repository
UV_CACHE_DIR=/tmp/uv-cache uv run python src/learning_common_lib/python基础/elasticsearch教程/templates/sync_repository.py
```

## 目录结构

```text
elasticsearch教程/
├── README.md
├── roadmap.md
├── architecture_map.md
├── best_practices.md
├── pitfalls.md
├── examples/
│   ├── 01_basics/
│   │   ├── 01_connect_and_info.py
│   │   └── 02_index_and_search.py
│   ├── 02_mapping_analysis/
│   │   ├── 01_field_types.py
│   │   └── 02_custom_analyzer.py
│   ├── 03_crud/
│   │   ├── 01_document_crud.py
│   │   └── 02_upsert_and_script.py
│   ├── 04_bulk/
│   │   ├── 01_bulk_helpers.py
│   │   └── 02_streaming_bulk.py
│   ├── 05_query_dsl/
│   │   ├── 01_bool_query.py
│   │   └── 02_full_text.py
│   ├── 06_aggregations/
│   │   ├── 01_metrics_and_buckets.py
│   │   └── 02_pipeline_and_date.py
│   ├── 07_pagination/
│   │   ├── 01_from_size.py
│   │   └── 02_search_after_pit.py
│   ├── 08_errors_recovery/
│   │   ├── 01_exception_types.py
│   │   └── 02_optimistic_concurrency.py
│   ├── 09_production/
│   │   ├── 01_alias_reindex.py
│   │   └── 02_async_client.py
│   ├── 10_dsl/
│   │   └── 01_document_orm.py
│   ├── 11_advanced_search/
│   │   ├── 01_highlight_source.py
│   │   ├── 02_collapse_dedup.py
│   │   ├── 03_knn_vector.py
│   │   └── 04_by_query_ops.py
│   └── 12_index_and_performance/
│       ├── 01_index_settings.py
│       ├── 02_index_template.py
│       └── 03_profile_msearch.py
├── templates/
│   ├── README.md
│   ├── __init__.py
│   ├── settings.py
│   ├── client_factory.py
│   ├── sync_repository.py
│   └── async_repository.py
└── smoke/
    └── run_all_examples.py
```

## 快速开始

先确认连接，再跑通最小检索闭环：

```bash
cd src/learning_common_lib/python基础/elasticsearch教程
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/01_basics/01_connect_and_info.py
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/01_basics/02_index_and_search.py
```

理解 mapping 和检索后，进入 Query DSL 和聚合：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/05_query_dsl/01_bool_query.py
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/06_aggregations/01_metrics_and_buckets.py
```

再看生产关注点：深度分页、乐观并发、alias 切换、异步客户端：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/07_pagination/02_search_after_pit.py
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/08_errors_recovery/02_optimistic_concurrency.py
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/09_production/01_alias_reindex.py
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/09_production/02_async_client.py
```

进阶检索与索引性能（向量检索、折叠、模板、慢查询剖析）：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/11_advanced_search/03_knn_vector.py
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/12_index_and_performance/01_index_settings.py
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/12_index_and_performance/03_profile_msearch.py
```

一键 smoke（会先探测 ES 连通性，并在用例间留间隔避免单节点过载）：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python smoke/run_all_examples.py
```

## 学习路线概览

详细路线见 [roadmap.md](roadmap.md)。

| 阶段 | 主题 | 你会学到 |
|------|------|----------|
| 1 | 连接与最小闭环 | `Elasticsearch`、`ping`、`info`、`index`、`search`、版本对齐 |
| 2 | mapping 与分析器 | `text` vs `keyword`、`analyze`、自定义 analyzer、multi-field |
| 3 | 文档 CRUD | `index`、`get`、`update`、`delete`、`doc_as_upsert`、script 累加 |
| 4 | 批量写入 | `helpers.bulk`、`streaming_bulk`、错误收集、429 退避重试 |
| 5 | Query DSL | `bool`(must/filter/should/must_not)、`match`、`match_phrase`、`multi_match`、`fuzziness` |
| 6 | 聚合 | `terms`、`range`、`stats`、`date_histogram`、管道聚合 `cumulative_sum` |
| 7 | 分页 | `from/size` 上限、`search_after` + Point In Time 深度翻页 |
| 8 | 错误与恢复 | 异常类型、`ignore_status`、`if_seq_no/if_primary_term` 乐观并发 |
| 9 | 生产实践 | alias + reindex 零停机切换、`AsyncElasticsearch` 并发 |
| 10 | 高级 DSL | `elasticsearch.dsl` 的 `Document`、`Search`、`Q` 面向对象 API |
| 11 | 高级检索 | `highlight`、`_source` 过滤、`collapse` 折叠去重、`dense_vector` kNN 向量检索与混合召回、`update_by_query`/`delete_by_query` |
| 12 | 索引与性能 | shard/replica/`refresh_interval` 调优、`forcemerge`、index template、`profile` 慢查询剖析、`msearch` 合并请求 |

## 核心原则

1. **客户端大版本必须对齐服务端**：8.x 服务端必须用 8.x 客户端，否则请求头版本协商失败。
2. **text 用于检索，keyword 用于过滤和聚合**：选错字段类型是最常见的“查不到/聚合报错”根因。
3. **mapping 不可变**：字段类型定了就改不了，变更走新索引 + reindex + alias 切换。
4. **精确过滤放 filter**：filter 不算分、可缓存，比放 must 更快。
5. **深度翻页用 search_after + PIT**：`from/size` 超过 `max_result_window`(默认 10000) 会报错且代价高。
6. **写入要幂等**：指定 `_id` + `doc_as_upsert` 或乐观并发控制，失败重跑不产生重复或脏写。
7. **应用读写 alias 而非物理索引名**：让索引重建和切换对应用透明。
8. **异步不等于无限并发**：`AsyncElasticsearch` 仍受连接池和服务端容量约束，需要超时和背压。

## 文档说明

| 文档 | 内容 |
|------|------|
| [roadmap.md](roadmap.md) | 从基础到生产实践的学习顺序和每个文件的教学定位 |
| [architecture_map.md](architecture_map.md) | Elasticsearch 知识点到检索工程链路的映射 |
| [best_practices.md](best_practices.md) | mapping、查询、写入、分页、生命周期、性能建议 |
| [pitfalls.md](pitfalls.md) | 常见错误、现象、根因和排查方式 |
| [templates/README.md](templates/README.md) | 可复用模板说明 |

## 学完后你应该具备的能力

- 能解释 Elasticsearch index、mapping、analyzer、document、query、aggregation、alias 的职责边界。
- 能用同步客户端创建索引、设计 mapping，写入文档并按全文和精确条件检索。
- 能写出 bool 复合查询、聚合分析和管道聚合，并区分 query/filter 上下文。
- 能用 `search_after` + PIT 做深度翻页，用乐观并发控制处理并发写入冲突。
- 能用 alias + reindex 做零停机的 mapping 变更，把同步仓储迁移到异步仓储。
- 能用 highlight、`_source` 过滤、collapse 折叠和 kNN 向量检索增强检索体验，并组合关键词与向量做混合召回。
- 能调优 shard/replica/refresh_interval，用 index template 管理时序索引族，用 profile/msearch 排查和优化查询。
- 能判断常见错误的根因，并知道生产环境的认证、版本对齐和资源边界。

## 来源记录

- context7 查询 `/elastic/elasticsearch-py`：确认 `Elasticsearch`/`AsyncElasticsearch` 连接、`index`、`search`、`indices.create(mappings/settings)`、`helpers.bulk`/`streaming_bulk`/`async_bulk`、`elasticsearch.dsl` 的 `Document`/`Search`/`Q`、`update_by_query`、聚合结构等 API 形态。
- context7 查询 `/elastic/elasticsearch-py`（生产配置与高级检索）：确认 `retry_on_status`/`http_compress`/`sniff_*` 客户端参数、`knn`/`dense_vector`、`highlight`、`collapse`/`inner_hits`、`source` 过滤、index template 等用法。
- 本地实测确认 8.19.3 客户端与 8.19.14 服务端兼容，9.4.1 客户端连 8.x 报 `media_type_header_exception`，据此把依赖固定为 `>=8.19,<9`。
- 本地实测验证 kNN（`dense_vector`+`knn`）、`highlight`、`collapse`、`_source` 过滤、`update_by_query`/`delete_by_query`、`forcemerge`、index template、`profile`、`msearch` 在 8.19.14 上的真实行为后再落地为示例。
- GitHub 代码搜索参考 `revjkee/aethernova` 的 `connectors/elasticsearch.py` 和 `oblivionvault-core` 的 `search_elastic.py`：学习生产连接器中同步/异步客户端复用、`retry_on_status`、`open_point_in_time` + 重试封装的模式。
- GitHub 代码搜索参考 `strawgate/es-knowledge-base-mcp` 的 `settings.py`：学习生产客户端 `http_compress=True`、`retry_on_status=(408,429,502,503,504)`、`retry_on_timeout=True` 的默认组合。
- GitHub 代码搜索参考 `openai/chatgpt-retrieval-plugin` 的 `elasticsearch_datastore.py` 和 `elastic/elasticsearch-labs`：学习 `dense_vector` mapping 和 `knn` 检索在 RAG/缓存场景的真实写法。
