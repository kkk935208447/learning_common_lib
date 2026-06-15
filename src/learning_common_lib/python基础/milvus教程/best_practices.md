# 最佳实践

本文记录可以直接迁移到项目里的结论性建议：应该怎么配、怎么命名、怎么查、怎么清理。原理和逐步推导见 [roadmap.md](roadmap.md) 的示例；常见错误和修复路径见 [pitfalls.md](pitfalls.md)。

## 连接与环境

| 场景 | 推荐做法 | 原因 |
|------|----------|------|
| 本地学习 | 使用 Milvus Lite URI，例如 `.milvus_tutorial/milvus_lite.db` | 不依赖 Docker，适合最小闭环 |
| 本地集成 | 使用 Docker Standalone，`MILVUS_URI=http://localhost:19530` | 更接近服务部署形态 |
| 云服务或开启认证的服务端 | 使用 Zilliz Cloud 或受管 Milvus，token 通过环境变量注入；完整项目也可用 PyMilvus 的 `user/password` 参数 | 避免把凭据写进代码 |
| CI 验证 | 默认运行 Milvus Lite smoke；Standalone/Zilliz Cloud 另设集成验证 | Lite 不需要外部部署，可覆盖真实 SDK 主路径 |

## Lite 与 Standalone 的关键差异

同一份 `MilvusClient` 代码，从 Lite 切到 Standalone 时要注意这些差异（详见 `09_standalone_ops/`）：

| 维度 | Milvus Lite | Milvus Standalone |
|------|-------------|-------------------|
| 部署 | 进程内，零依赖 | milvus + etcd（元数据）+ MinIO（对象存储）三件套 |
| 加载生命周期 | 隐藏，建好即可搜 | 检索前要确认集合已加载；`release` 后必须重新 `load_collection`，否则报 `collection not loaded` |
| segment/存储 | 单文件，无独立存储层 | 数据落对象存储，需要 `flush` 封口、`compact` 回收 |
| 异步建索引 | 不支持（触发未实现 RPC） | `AsyncMilvusClient` 支持异步 DDL |
| `search_iterator` | 回退到 V1 | 完整 V2 |
| 适用阶段 | 学习、最小闭环、单测 | 集成、压测、生产 |

实践建议：
- 用 `create_collection(schema=..., index_params=...)` 创建时通常会自动建索引并加载；但上线或运维脚本仍应在检索前用 `get_load_state` 确认状态。
- 写入完成后如果要做导入验收，可在批次边界 `flush` 一次并确认集合已 load；不要把 `flush` 当成常规写后读手段。
- 冷集合 `release` 省内存，热集合保持 `load`；用 `get_load_state` 做运维判断。
- `flush`/`compact` 是有成本的服务端操作，别在写入热路径里频繁调用。

## schema 设计

- 主键使用稳定 ID，例如 `document_id + chunk_no + version` 的哈希或拼接值。
- 文本字段设置明确 `max_length`，避免超长 chunk 写入失败。
- 标量过滤字段应在 schema 中显式声明，例如 `source`、`tenant_id`、`document_id`。
- 教程关闭 `enable_dynamic_field`，让字段错误尽早暴露；生产中只有确实需要灵活 metadata 时才打开。
- 向量维度必须来自 embedding 模型配置，不能在多处硬编码。

## 索引与度量

| 参数 | 教程默认 | 生产建议 |
|------|----------|----------|
| `index_type` | `AUTOINDEX` | 先用官方自动索引，数据规模和延迟目标明确后再专项调优 |
| `metric_type` | `COSINE` | 文本 embedding 常用；如果使用 IP，需要确认是否已归一化 |
| `search_params` | `{"metric_type": "COSINE"}` | HNSW/IVF 等索引再补 `ef`、`nprobe` 等搜索参数 |
| `limit` | 2-3 | RAG 中通常先召回更多候选，再交给 reranker 或上下文压缩 |

常见索引选型：

| 索引类型 | 关键构建参数 | 关键搜索参数 | 适合场景 |
|----------|--------------|--------------|----------|
| `AUTOINDEX` | 无 | `metric_type` | 入门、云端自动调优、缺少压测数据的阶段 |
| `FLAT` | 无 | `metric_type` | 小数据集、召回正确性基线 |
| `IVF_FLAT` | `nlist` | `nprobe` | 中等规模，想显式控制召回和延迟 |
| `IVF_SQ8` | `nlist` | `nprobe` | 希望减少内存占用，接受量化误差 |
| `IVF_PQ` | `nlist`、`m`、`nbits` | `nprobe` | 大规模压缩存储，召回需重点验证 |
| `HNSW` | `M`、`efConstruction` | `ef` | 低延迟、高召回在线检索 |
| `DISKANN` | 依部署能力而定 | `search_list` | 超大规模、磁盘型 ANN |
| `SCANN` | `nlist`、`with_raw_data` | `nprobe`、`reorder_k` | 候选召回后重排 |
| `SPARSE_INVERTED_INDEX` | `inverted_index_algo` | `BM25` 或 `IP` | 稀疏向量、全文检索、混合检索 |

参数判断：

- `nprobe` 越大通常召回越高、查询越慢。
- `ef` 越大通常召回越高、查询越慢。
- `M` 和 `efConstruction` 越大，HNSW 构建越慢、内存越高，但图质量通常更好。
- `radius` 和 `range_filter` 用于范围检索，阈值必须按 metric type 和业务样本校准。
- `m` 要和向量维度兼容，使用 `IVF_PQ` 前必须确认压缩误差可接受。

## 写入策略

- 批量导入使用 `upsert` 和稳定主键，支持失败重跑。
- 空批次直接跳过，不要调用 Milvus。
- 写入前校验维度、NaN、无穷大和零向量。
- 大批量导入应分批，并记录批次号、成功数量、失败数量和耗时。
- 删除数据优先按文档或租户过滤删除，谨慎使用 `drop_collection`。

## 查询策略

- 在线查询通常先生成 query embedding，再调用 `search`。
- 如果有权限、租户、来源或时间范围，优先用 scalar filter 缩小搜索空间。
- `query` 是标量查询，不计算向量相似度；`search` 是向量检索，可叠加 filter。
- 大结果集导出或批量巡检使用 `query_iterator`，不要一次性把所有行拉进内存。
- 需要分批消费较大的 topK 检索结果时使用 `search_iterator`，并在 `finally` 中关闭 iterator。
- RAG 检索常按 `document_id` 使用 `group_by_field` 去重，避免同一文档多个相邻 chunk 挤占上下文窗口。
- 不要把用户输入未经处理直接拼进 filter 字符串。生产中应使用白名单字段、枚举值或参数化封装。
- 检索返回的 `distance`/`score` 含义取决于 metric type，不能跨 metric 直接比较。

## 一致性级别

| 级别 | 适合场景 | 取舍 |
|------|----------|------|
| `Strong` | 写入后马上验证、离线导入 smoke、需要强写后读语义的后台任务 | 可见性最强，分布式环境下延迟和可用性压力更高 |
| `Bounded` | 多数在线检索默认值 | 在延迟和新鲜度之间折中 |
| `Eventually` | 更重吞吐、能接受短暂旧数据的读路径 | 可能读到较旧结果，不适合写后立即验证 |
| `Session` | 同一客户端会话内希望保持相对一致视图 | 依赖会话语义，跨客户端仍需明确验证 |

教程多数示例显式使用 `Strong`，目的是让本地 smoke 和写后读结果稳定；生产默认可以从 `Bounded` 开始，再按业务新鲜度要求调整。

## partition 与 alias

- partition 适合粗粒度隔离，例如少量租户、大类目或冷热数据；不要为每个用户创建 partition。
- partition key 适合高基数字段的自动路由，例如 `tenant_id`、`namespace`；字段值不能为空。
- 多数权限、来源、时间范围过滤优先用 scalar filter，而不是无限扩展 partition。
- 在线服务优先查询 alias，例如 `kb_current`，不要直接绑定 `kb_docs_v1`。
- 索引重建推荐创建新 collection，数据校验通过后用 `alter_alias` 切换。
- 回滚时把 alias 指回旧 collection，比原地覆盖索引更可控。

## 混合检索

- dense 向量解决语义相似度，sparse/BM25 解决关键词和专有名词精确匹配。
- Milvus hybrid search 使用多个 `AnnSearchRequest`，每个向量字段一个请求。
- `RRFRanker` 适合不想手工调权重的初始融合；`WeightedRanker` 适合明确 dense/sparse 权重的场景。
- BM25 需要在 schema 创建时配置 `enable_analyzer=True`、`DataType.SPARSE_FLOAT_VECTOR` 和 `FunctionType.BM25`。
- 如果需要新增 BM25 字段，通常创建新 collection 后用 alias 切换，不建议在旧 collection 上硬补。

## 示例与模板导入

- `examples/` 示例优先自包含，允许重复少量 helper，让读者打开单文件即可学习。
- `templates/` 优先使用包内相对导入，便于迁移到真实项目后保持模块边界。
- 需要直接运行单个模板文件时，模板可以在相对导入失败后回退到 `templates.*` 绝对导入。
- smoke 同时验证 `python -m learning_common_lib.python基础.milvus教程.templates.<module>` 和 `templates/<module>.py` 两种运行方式。

## 同步与异步客户端选择

| 客户端 | 适合 | 不适合 |
|--------|------|--------|
| `MilvusClient` | 教程、脚本、离线索引构建、运维工具 | FastAPI 高并发请求路径 |
| `AsyncMilvusClient` | FastAPI、异步 worker、批量并发查询 | 初学最小闭环、简单一次性脚本 |

异步客户端建议：

- 在服务启动时创建，在服务关闭时关闭。
- 使用 `async with` 或 lifespan 管理生命周期。
- 批量搜索必须加并发上限，例如 `asyncio.Semaphore`。
- 每次调用设置合理超时，不要让请求无限等待。
- PyMilvus 3.0 源码中仍标注 `AsyncMilvusClient` 为实验性类，升级 SDK 后必须跑集成 smoke。

## 清理边界

- 教程集合统一使用 `learning_milvus_` 前缀。
- 示例只删除自己创建的集合名。
- 不提供“删除所有集合”的默认脚本。
- 生产环境应把 destructive 操作放在受控运维命令里，并要求显式确认环境和前缀。

## 可观测性

生产接入后至少记录：

- collection 名称和 schema 版本。
- embedding 模型名和维度。
- 写入批次大小、耗时、成功数量、失败数量。
- search 的 `limit`、filter、耗时、返回数量。
- Milvus 连接错误、超时、重试次数。
- 降级路径，例如返回空结果、切备用向量库或提示稍后重试。
