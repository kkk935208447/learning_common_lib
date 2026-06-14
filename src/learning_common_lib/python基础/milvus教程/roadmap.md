# 学习路线（roadmap）

本文回答“应该按什么顺序学 Milvus 教程，以及每个示例为什么放在这个位置”。先用 [README.md](README.md) 完成环境准备和快速开始，再按本文逐个运行示例；需要工程分层时看 [architecture_map.md](architecture_map.md)，需要结论性取舍时看 [best_practices.md](best_practices.md)。

## 版本要求

- Python `>=3.11,<3.12`
- `pymilvus[milvus-lite]>=3.0.0`
- 第一、二阶段包含部分纯 Python 协议和 schema 构造示例，用于先理解数据边界。
- 第三到第八阶段默认使用 Milvus Lite DB 真实执行 API；也可通过 `MILVUS_URI=http://localhost:19530` 连接 Standalone。
- 若本机配置了 HTTP/HTTPS 代理，示例会自动把 `127.0.0.1,localhost` 加入 `NO_PROXY/no_proxy`，避免 Milvus Lite 本机 gRPC 连接走代理。
- `examples/` 示例优先自包含，允许重复少量 helper，以保证打开单个文件就能理解。

## 阶段一：向量数据协议（01_basics/）

**学什么**：先理解向量库接收的不是“文档”，而是带稳定主键、文本、来源、chunk 序号和 embedding 的行数据。

**为什么在这里**：很多 Milvus 问题不是数据库问题，而是 embedding 维度、NaN、零向量、主键和 metadata 协议没有提前约束。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 1 | `01_vector_protocol.py` | LangChain `Document` 协议、行数据转换、L2 归一化 | 输出的 Milvus row 字段是否完整 |
| 2 | `02_dimension_validation.py` | 维度校验、非法数值、零向量 | 错误是否在客户端边界暴露 |

**关键收获**：知道写入 Milvus 前必须先定义数据协议，而不是直接把任意 dict 塞给 SDK。

## 阶段二：schema 与 index（02_schema_index/）

**学什么**：构造 collection schema、主键、`FLOAT_VECTOR`、标量字段、`AUTOINDEX` 和 `COSINE`。

**为什么在这里**：schema 和 index 是 Milvus 的工程边界。后续插入、搜索、过滤都依赖字段名、字段类型和度量方式。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 3 | `01_build_schema_and_index.py` | `create_schema`、`DataType`、`prepare_index_params` | 字段、维度、索引参数是否符合预期 |
| 4 | `02_collection_name_policy.py` | 集合命名、前缀隔离、清理边界 | 集合名是否始终带 `learning_milvus_` 前缀 |

**关键收获**：能在不连接服务的情况下先审查 schema/index 设计，减少运行时排错成本。

## 阶段三：同步 CRUD 与过滤（03_filter_and_crud/）

**学什么**：用同步 `MilvusClient` 完成真实 collection 创建、写入、搜索、标量过滤、查询和删除。

**为什么在这里**：同步客户端调用链直观，适合建立 Milvus 核心 API 心智模型。异步客户端放到后面，避免一开始同时学习数据库概念和并发概念。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 5 | `01_lite_insert_search.py` | create → upsert → search → drop | top hit 是否命中 Milvus 相关文档 |
| 6 | `02_scalar_filter_query_delete.py` | `search(filter=...)`、`query`、`delete` | filter 是否限定 source，delete 是否只删目标来源 |

**关键收获**：能用 `MilvusClient` 跑通单机语义搜索闭环，并知道 query 和 search 的差别。

## 阶段四：错误恢复与幂等（04_errors_and_recovery/）

**学什么**：区分参数错误、数据错误、连接错误和可重试错误；用稳定主键和 `upsert` 支持导入任务重跑；理解一致性级别对写后读链路的影响。

**为什么在这里**：RAG 索引构建经常要批量导入和失败重跑。如果主键不稳定或盲目 retry，会产生重复数据或隐藏真实错误。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 7 | `01_client_side_errors.py` | 参数错误、空批次、非法集合名 | 哪些错误不应该进入 Milvus |
| 8 | `02_idempotent_upsert.py` | 幂等导入、稳定主键、重复执行 | 同一批 upsert 两次后记录数不膨胀 |
| 9 | `03_consistency_levels.py` | `Strong`、`Bounded`、`Eventually`、`Session` | collection 默认值和单次请求覆盖的区别 |

**关键收获**：能为索引构建任务设计可重跑的数据写入策略，并知道“写完立刻搜不到”要从 flush/load、索引和一致性三个方向排查。

## 阶段五：异步客户端（05_async_client/）

**学什么**：在基础 API 已经掌握后，使用 `AsyncMilvusClient` 的 `async with`、`await`、`asyncio.gather` 和并发上限。

**为什么在这里**：异步客户端适合 FastAPI、异步 worker、批量查询等场景，但它不改变 Milvus 的数据模型。先学同步 API，再学习异步生命周期，认知负担更低。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 10 | `01_async_search_many.py` | 同步离线建库、异步并发 search | 批量搜索是否有明确并发上限 |
| 11 | `02_async_lifecycle_policy.py` | 服务启动/关闭、连接复用、限流 | 在线检索复用同一个异步客户端 |

**关键收获**：能把 Milvus 检索接入异步服务，同时避免每个请求新建连接或无限并发。

## 阶段六：索引与搜索参数（06_index_and_search_params/）

**学什么**：系统认识 Milvus 常见索引类型、构建参数、搜索参数、iterator 分批读取和 grouping search 去重。

**为什么在这里**：基础 CRUD 只解决“能用”，生产检索还需要理解不同索引的召回、延迟、内存和磁盘取舍。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 12 | `01_index_catalog.py` | 索引类型参数目录 | 每种索引适合什么场景 |
| 13 | `02_build_multiple_index_params.py` | 多向量字段索引 | dense/image/sparse 字段如何分别配置 |
| 14 | `03_range_search_params.py` | `nprobe`、`ef`、`radius`、`range_filter` | 搜索参数如何影响召回和延迟 |
| 15 | `04_iterators_large_results.py` | `query_iterator`、`search_iterator`、`batch_size` | 大结果集为什么要分批读取并显式 close |
| 16 | `05_grouping_search.py` | `group_by_field`、`group_size`、`strict_group_size` | 同一文档多 chunk 命中时如何按 `document_id` 去重 |

**关键收获**：能根据场景说清楚为什么先用 `AUTOINDEX`，何时评估 `IVF_FLAT`、`HNSW`、`DISKANN`、`SCANN` 或稀疏索引，也能处理大结果集分页和 RAG 文档级去重。

## 阶段七：partition 与 alias（07_partitions_aliases/）

**学什么**：手动 partition 的粗粒度隔离、partition key 的自动路由，以及 alias 支持蓝绿索引切换。

**为什么在这里**：真实知识库常有租户、版本、灰度和回滚需求。Milvus 不只是存向量，也要配合发布流程设计。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 17 | `01_partition_lifecycle.py` | create/load/release/drop partition | partition_names 和 scalar filter 的职责差别 |
| 18 | `02_alias_switching.py` | create_alias、alter_alias、回滚 | 在线服务为什么应查询 alias |
| 19 | `03_partition_key.py` | `is_partition_key=True`、租户字段自动路由 | partition key 和手动 partition 的适用边界 |

**关键收获**：能设计 collection 版本切换流程，避免在生产服务里直接绑定物理 collection 名，也能区分手动 partition、partition key 和 scalar filter。

## 阶段八：混合检索（08_hybrid_search/）

**学什么**：dense 向量、sparse 向量、BM25 和 hybrid rerank 的 API 结构。

**为什么在这里**：RAG 只用 dense embedding 容易漏掉关键词精确匹配；混合检索能结合语义召回和词项召回。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 20 | `01_hybrid_request.py` | `AnnSearchRequest`、`RRFRanker`、`WeightedRanker` | 每个向量字段一个请求，再用 ranker 融合 |
| 21 | `02_bm25_schema.py` | `SPARSE_FLOAT_VECTOR`、`FunctionType.BM25`、analyzer | BM25 必须在 schema 创建期设计 |

**关键收获**：能看懂 Milvus hybrid search 的请求结构，并知道 BM25 schema 不是查询时临时参数。

## 学完示例后

阅读 `templates/`：

1. `settings.py`：统一配置和集合命名。
2. `vector_utils.py`：数据协议和向量校验。
3. `sync_repository.py`：同步脚本/离线任务骨架。
4. `async_repository.py`：异步服务/worker 骨架。
5. `index_catalog.py`：索引选型和参数目录。
