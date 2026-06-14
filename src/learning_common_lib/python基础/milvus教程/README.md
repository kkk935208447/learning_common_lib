# Milvus 教程（基础 + 异步客户端 + 高级检索）

本教程教你用 Milvus Lite 跑通从文档 chunk、schema/index、写入检索、异步客户端到 hybrid search 的完整 RAG 检索链路。

这份教程放在 `src/learning_common_lib/python基础/` 下，面向已经掌握 Python 基础、准备学习向量数据库和 RAG 检索链路的开发者。建议先读本文完成环境准备和快速开始，再按 [roadmap.md](roadmap.md) 的顺序逐个运行示例；遇到工程取舍时看 [architecture_map.md](architecture_map.md) 和 [best_practices.md](best_practices.md)，排查问题时看 [pitfalls.md](pitfalls.md)。

教程采用“先同步、后异步、再高级检索”的路线。前几节用同步 `MilvusClient` 建立 collection、schema、index、insert、search、filter、delete 的完整心智模型；基础稳定后，再进入 `AsyncMilvusClient`、索引参数、iterator、grouping search、partition、alias、dense+sparse hybrid search 等高级主题。

## 适合人群

- 想从零跑通 Milvus 向量检索闭环的 Python 开发者。
- 正在做 RAG、AgenticRAG、语义搜索或知识库检索的工程师。
- 已经学过本仓库 `asyncio教程`，希望把异步客户端接入服务端的同学。
- 想理解 Milvus collection、schema、index、filter、partition、alias、hybrid search 生命周期，而不是只调用封装库的同学。

## 环境要求

| 项目 | 要求 | 说明 |
|------|------|------|
| Python | `>=3.11,<3.12` | 与当前仓库一致 |
| 依赖 | `pymilvus[milvus-lite]>=3.0.0` | 已写入 `pyproject.toml` |
| 本地模式 | Milvus Lite | 示例默认使用 `.milvus_tutorial/*.db`，每个真实示例有独立 DB 文件 |
| 服务模式 | Milvus Standalone 或 Zilliz Cloud | 通过 `MILVUS_URI` 和 `MILVUS_TOKEN` 注入 |
| 缓存目录 | 建议 `UV_CACHE_DIR=/tmp/uv-cache` | 避免受限环境写用户全局缓存 |

安装依赖：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync
```

默认使用 Milvus Lite：

```bash
cd src/learning_common_lib/python基础/milvus教程
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/03_filter_and_crud/01_lite_insert_search.py
```

如果使用 Docker Standalone：

```bash
export MILVUS_URI=http://localhost:19530
export MILVUS_TOKEN=root:Milvus
cd src/learning_common_lib/python基础/milvus教程
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/03_filter_and_crud/01_lite_insert_search.py
```

> Milvus Lite 会在当前 Python 进程内启动本机 gRPC 服务，不需要额外部署 Milvus。若你的环境设置了 HTTP/HTTPS 代理，请确保 `NO_PROXY` 和 `no_proxy` 包含 `127.0.0.1,localhost`；教程示例和 smoke 已自动补齐这两个变量。

## 示例独立性约定

`examples/` 下的每个 `.py` 文件尽量自包含。即使多个示例重复了向量归一化、连接配置或 collection 初始化代码，也优先让读者打开单个文件就能直接理解。本目录的 `templates/` 是迁移到真实项目时可复用的骨架，不是基础示例的隐式前置依赖。

模板优先使用包内相对导入，同时保留直接运行单个模板文件时的受控回退路径。真实项目中推荐绝对导入到具体子模块，IDE 可以点击进入源码：

```bash
cd /home/shayuer/document/learning_some/learning_common_lib
UV_CACHE_DIR=/tmp/uv-cache uv run python -m learning_common_lib.python基础.milvus教程.templates.index_catalog
UV_CACHE_DIR=/tmp/uv-cache uv run python src/learning_common_lib/python基础/milvus教程/templates/index_catalog.py
```

## 目录结构

```text
milvus教程/
├── README.md
├── roadmap.md
├── architecture_map.md
├── best_practices.md
├── pitfalls.md
├── examples/
│   ├── 01_basics/
│   │   ├── 01_vector_protocol.py
│   │   └── 02_dimension_validation.py
│   ├── 02_schema_index/
│   │   ├── 01_build_schema_and_index.py
│   │   └── 02_collection_name_policy.py
│   ├── 03_filter_and_crud/
│   │   ├── 01_lite_insert_search.py
│   │   └── 02_scalar_filter_query_delete.py
│   ├── 04_errors_and_recovery/
│   │   ├── 01_client_side_errors.py
│   │   ├── 02_idempotent_upsert.py
│   │   └── 03_consistency_levels.py
│   ├── 05_async_client/
│   │   ├── 01_async_search_many.py
│   │   └── 02_async_lifecycle_policy.py
│   ├── 06_index_and_search_params/
│   │   ├── 01_index_catalog.py
│   │   ├── 02_build_multiple_index_params.py
│   │   ├── 03_range_search_params.py
│   │   ├── 04_iterators_large_results.py
│   │   └── 05_grouping_search.py
│   ├── 07_partitions_aliases/
│   │   ├── 01_partition_lifecycle.py
│   │   ├── 02_alias_switching.py
│   │   └── 03_partition_key.py
│   └── 08_hybrid_search/
│       ├── 01_hybrid_request.py
│       └── 02_bm25_schema.py
├── templates/
│   ├── README.md
│   ├── __init__.py
│   ├── index_catalog.py
│   ├── settings.py
│   ├── vector_utils.py
│   ├── sync_repository.py
│   └── async_repository.py
└── smoke/
    └── run_all_examples.py
```

## 快速开始

先运行不依赖 Milvus 服务的基础示例：

```bash
cd src/learning_common_lib/python基础/milvus教程
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/01_basics/01_vector_protocol.py
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/02_schema_index/01_build_schema_and_index.py
```

再运行真实 Milvus 闭环：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/03_filter_and_crud/01_lite_insert_search.py
```

完成基础后，再看异步客户端：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/05_async_client/01_async_search_many.py
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/05_async_client/02_async_lifecycle_policy.py
```

继续学习高级参数和混合检索：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/06_index_and_search_params/01_index_catalog.py
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/06_index_and_search_params/04_iterators_large_results.py
UV_CACHE_DIR=/tmp/uv-cache uv run python examples/08_hybrid_search/01_hybrid_request.py
```

一键 smoke：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python smoke/run_all_examples.py
```

## 学习路线概览

详细路线见 [roadmap.md](roadmap.md)。

| 阶段 | 主题 | 你会学到 |
|------|------|----------|
| 1 | 向量数据协议 | LangChain `Document`、embedding 维度、归一化、Milvus 行数据 |
| 2 | schema 与 index | 字段类型、主键、`FLOAT_VECTOR`、`AUTOINDEX`、`COSINE` |
| 3 | 同步 CRUD 与过滤 | `MilvusClient`、写入、搜索、标量过滤、查询、删除 |
| 4 | 错误恢复与幂等 | 参数错误、连接错误、稳定主键、`upsert`、一致性级别 |
| 5 | 异步客户端 | `AsyncMilvusClient`、`async with`、并发搜索、服务生命周期 |
| 6 | 索引与搜索参数 | `FLAT`、`IVF_FLAT`、`HNSW`、`DISKANN`、`SCANN`、`SPARSE_INVERTED_INDEX`、`nprobe`、`ef`、`radius`、iterator、grouping search |
| 7 | partition 与 alias | `create_partition`、`partition_names`、`partition key`、`create_alias`、`alter_alias`、蓝绿切换 |
| 8 | 混合检索 | `AnnSearchRequest`、`RRFRanker`、`WeightedRanker`、BM25 schema/function |

## 核心原则

1. **先校验向量，再写 Milvus**：维度错误、NaN、零向量都应在 embedding 边界失败。
2. **先同步跑通，再引入异步**：同步客户端更适合学习核心对象模型；异步客户端适合服务端并发。
3. **collection 命名必须受控**：教程统一使用 `learning_milvus_` 前缀，清理只作用于显式集合。
4. **索引和度量方式一起设计**：示例默认 `AUTOINDEX + COSINE`，后续单独比较 IVF、HNSW、DISKANN、SCANN、稀疏索引。
5. **批量导入使用稳定主键和 upsert**：失败重跑不应产生重复向量。
6. **异步也要限流**：`AsyncMilvusClient` 不代表可以无限并发，服务端仍需要连接池、超时和背压。
7. **高级能力必须真实跑通再总结取舍**：索引、iterator、grouping search、partition、alias、hybrid search 都用 Milvus Lite DB 运行，文档只总结已验证的 API 边界。

## 文档说明

| 文档 | 内容 |
|------|------|
| [roadmap.md](roadmap.md) | 从基础到异步客户端和高级检索的学习顺序 |
| [architecture_map.md](architecture_map.md) | Milvus 知识点到 RAG 工程链路的映射 |
| [best_practices.md](best_practices.md) | 参数、生命周期、性能、部署建议 |
| [pitfalls.md](pitfalls.md) | 常见错误、现象、根因和排查方式 |
| [templates/README.md](templates/README.md) | 可复用模板说明 |

## 学完后你应该具备的能力

- 能解释 Milvus collection、schema、index、load、search、query、partition、alias 的职责边界。
- 能用 `MilvusClient` 创建本地教学集合，写入 LangChain `Document` 并按向量和标量条件检索。
- 能判断 `insert`、`upsert`、`delete`、`drop_collection`、iterator、grouping search 和 consistency level 的生产风险。
- 能把同步仓储迁移到异步仓储，并在服务生命周期内正确创建和关闭客户端。
- 能为 RAG 检索链路设计基础的向量数据协议、错误恢复策略、索引参数和 hybrid search 方案。

## 来源记录

- context7 查询 `/websites/milvus_io_v2_6_x`：确认 `MilvusClient` 基本工作流、schema、index_params、`AUTOINDEX`、`COSINE`、Milvus Lite URI、Standalone URI/token。
- context7 查询 `/milvus-io/pymilvus`：确认 `MilvusClient` 方法签名、`AsyncMilvusClient` 实验性说明、异步 `search/query/insert/upsert` 形态。
- context7 查询 Milvus 2.6 索引和搜索参数：确认 `FLAT`、`IVF_FLAT`、`HNSW`、`DISKANN`、`SCANN`、`SPARSE_INVERTED_INDEX`、`nlist`、`nprobe`、`M`、`efConstruction`、`ef`、`radius`、`range_filter`、BM25 等参数。
- context7 查询 Milvus 2.6 iterator、grouping search、partition key、consistency、partition、alias、hybrid search：确认 `query_iterator`、`search_iterator`、`group_by_field`、`is_partition_key=True`、`Strong/Bounded/Eventually/Session`、`create_partition`、`partition_names`、`create_alias`、`alter_alias`、`AnnSearchRequest`、`RRFRanker`、`WeightedRanker` 和 BM25 Function 结构。
- GitHub 代码搜索参考 `open-webui/open-webui`：学习向量库适配器中 collection 前缀、metadata、filter、delete 的封装方式。
- GitHub 代码搜索参考 `serengil/deepface`：学习按模型参数生成集合名、批量写入、`COSINE/L2` 度量选择。
- GitHub 代码搜索参考 `milvus-io/pymilvus` 的 `examples/simple_async.py`：学习 `AsyncMilvusClient` 的 `async with`、并行插入和并行搜索模式。
- GitHub 代码搜索参考 `milvus-io/pymilvus` 的 `examples/hybrid_search.py`：学习多向量字段、`AnnSearchRequest`、`RRFRanker`、`WeightedRanker` 的真实 SDK 写法。
- GitHub 代码搜索参考 `milvus-io/pymilvus`、`milvus-io/milvus-doc-examples`、`huangjia2019/rag-in-action`、`zilliztech/VectorDBBench`：学习 iterator、grouping search 和 partition key 的实际使用模式。
- GitHub 代码搜索参考 `vstorm-co/full-stack-ai-agent-template`：学习异步 RAG vector store 中 `_ensure_collection`、文档级删除和查询结果映射模式。
