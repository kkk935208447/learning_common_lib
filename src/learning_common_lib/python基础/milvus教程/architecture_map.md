# 架构映射

本文回答“教程里的每个概念在真实 RAG 工程中对应哪一层”。如果你还没有跑通示例，先看 [README.md](README.md) 和 [roadmap.md](roadmap.md)；如果你已经要迁移到项目结构，再结合 [best_practices.md](best_practices.md) 判断哪些逻辑应该放到配置层、仓储层或检索策略层。

## 从教程示例到 RAG 工程链路

```text
原始文档
  ↓ 解析、切分、清洗
LangChain Document(id, page_content, metadata)
  ↓ embedding 生成
metadata["vector"]: list[float]
  ↓ 客户端边界校验
ensure_vector / l2_normalize
  ↓ 向量库写入
Milvus collection(schema + index)
  ↓ 在线查询
query embedding + scalar filter
  ↓ 返回候选上下文
rerank / prompt / answer
```

## 知识点到工程分层

| 教程知识点 | 工程分层 | 真实职责 |
|------------|----------|----------|
| LangChain `Document` | 领域模型层 | 使用 `id` 承载稳定主键，`page_content` 承载文本，`metadata` 承载来源、chunk 序号和向量 |
| `ensure_vector` | 数据质量边界 | 阻止维度错误、NaN、零向量进入向量库 |
| schema | 基础设施层 | 固化 collection 字段、主键、向量字段和标量字段 |
| index_params | 基础设施层 | 决定向量检索性能、召回和成本 |
| `SyncMilvusRepository` | 离线索引构建层 | 批量导入、重跑、清理教程集合 |
| `AsyncMilvusRepository` | 在线检索层 | 服务端并发检索、连接生命周期、限流 |
| `filter` | 检索策略层 | 按租户、文档来源、权限、时间范围缩小搜索空间 |
| `query_iterator` / `search_iterator` | 批量读取层 | 分批导出或消费大结果集，避免一次性拉取过多数据 |
| `group_by_field` | 文档级去重层 | 同一文档多个 chunk 命中时按 `document_id` 返回代表结果 |
| `upsert` | 任务恢复层 | 支持失败重跑和幂等导入 |
| consistency level | 读写可见性层 | 在写后读、吞吐、可用性之间选择 `Strong`、`Bounded`、`Eventually` 或 `Session` |
| index profile | 检索调优层 | 区分构建参数、搜索参数、metric 和索引适用场景 |
| partition | 数据布局层 | 管理少量粗粒度物理分区，例如版本、租户大类或冷热数据 |
| partition key | 自动分区路由层 | 用高基数字段让 Milvus 自动路由，例如租户或 namespace |
| alias | 发布控制层 | 把在线服务从物理 collection 名中解耦，支持蓝绿切换和回滚 |
| hybrid search | 召回融合层 | 用 dense、sparse、BM25 多路召回后统一排序 |

## 示例与模板边界

```text
examples/
  ↓ 每个文件独立运行，允许重复少量 helper
学习单个 API、参数或生产取舍

templates/
  ↓ 包内使用相对导入，包外使用绝对导入
迁移到真实项目时复用配置、校验、同步仓储和异步仓储骨架
```

`examples/` 不依赖 `templates/`，这样读者点击任意示例文件都能看到完整上下文。`templates/` 适合在真实项目里做显式导入，例如：

```python
from learning_common_lib.python基础.milvus教程.templates.index_catalog import get_index_profile
from learning_common_lib.python基础.milvus教程.templates.sync_repository import SyncMilvusRepository
```

模板模块内部优先保留 `from .settings import load_settings` 这类相对导入，方便 IDE 从包内跳转；直接运行单个模板文件时，再回退到 `templates.settings` 这类绝对导入。

## 同步客户端链路

```text
脚本入口
  ↓ load_settings()
SyncMilvusRepository
  ↓ ensure_collection(reset=True)
MilvusClient.create_collection(schema, index_params)
  ↓ upsert_chunks()
MilvusClient.upsert(data=[...])
  ↓ search()
MilvusClient.search(data=[query_vector], filter=...)
  ↓ drop_collection()
清理教程专用集合
```

同步链路适合：

- 本地学习。
- CLI 工具。
- 离线索引构建任务。
- 运维脚本。

同步链路不适合：

- FastAPI 请求路径中的高并发检索。
- 需要和其他异步 I/O 合并调度的 worker。
- 需要统一取消、超时和优雅关闭的服务生命周期。

## 异步客户端链路

```text
服务启动 / worker 启动
  ↓ async with AsyncMilvusRepository()
AsyncMilvusClient 建立连接
  ↓ ensure_collection()
异步检查 collection / 创建 schema / load
  ↓ search_many()
Semaphore 限制并发
  ↓ await client.search(...)
批量返回候选文档
  ↓ 服务关闭
await client.close()
```

异步客户端放在后半段学习，是因为它主要解决服务端运行时问题，而不是改变 Milvus 的核心数据模型。读者先掌握同步 API 后，再迁移到异步写法，能更清楚地区分“向量库概念”和“Python 并发模型”。

## 索引参数分层

```text
业务目标
  ↓ 召回率、延迟、内存、磁盘、构建时间
index_type + metric_type
  ↓ create_collection / create_index 阶段
构建参数：nlist / M / efConstruction / m / nbits / inverted_index_algo
  ↓ search 阶段
搜索参数：nprobe / ef / radius / range_filter / reorder_k / drop_ratio_search
  ↓ 大结果集与 RAG 去重
iterator 分批读取 / group_by_field 文档级去重
  ↓ 线上评估
召回评测集 + 延迟指标 + 资源指标
```

构建参数决定索引结构，改动后通常需要重建索引或创建新 collection。搜索参数控制单次查询的召回范围，可以按接口、租户、业务等级做配置，但必须有上限。

| 索引方向 | 典型索引 | 关键参数 | 生产关注点 |
|----------|----------|----------|------------|
| 自动索引 | `AUTOINDEX` | 主要关注 `metric_type` | 适合入门和云端自动调优，但仍要压测 |
| 精确基线 | `FLAT` | 无构建参数 | 小数据集或召回对照，数据大后成本高 |
| 倒排聚类 | `IVF_FLAT`、`IVF_PQ` | `nlist`、`m`、`nbits`、`nprobe` | 需要校准召回和压缩损失 |
| 图索引 | `HNSW` | `M`、`efConstruction`、`ef` | 延迟低、内存高，适合在线检索 |
| 磁盘/重排 | `DISKANN`、`SCANN` | `search_list`、`reorder_k` | 依赖部署能力和真实硬件压测 |
| 稀疏检索 | `SPARSE_INVERTED_INDEX` | `inverted_index_algo`、`drop_ratio_search` | 适合 BM25、关键词召回和混合检索 |

## partition 与 alias 发布链路

```text
离线构建新版本 collection：kb_docs_v2
  ↓ 写入、索引、load、抽样 search/query 验证
alias 当前指向：kb_current -> kb_docs_v1
  ↓ alter_alias(collection_name="kb_docs_v2", alias="kb_current")
在线服务无感切到新版本
  ↓ 监控错误率、召回、延迟
异常时 alter_alias 回旧版本：kb_current -> kb_docs_v1
```

手动 partition 更适合少量粗粒度物理隔离；partition key 更适合多租户或 namespace 这类高基数字段的自动路由；权限、来源、时间范围这类高频细粒度条件仍优先使用 scalar filter。alias 负责发布控制，在线服务应该依赖稳定 alias，而不是把物理 collection 名写进请求路径。

## hybrid search 链路

```text
query text
  ↓ dense embedding
AnnSearchRequest(anns_field="dense_vector", metric_type="COSINE")
  ↓ sparse/BM25 表达
AnnSearchRequest(anns_field="sparse_vector", metric_type="BM25" 或 "IP")
  ↓ hybrid_search
RRFRanker 或 WeightedRanker
  ↓ output_fields
统一候选列表
```

BM25 不是查询时临时打开的参数，而是在 schema 创建期通过文本字段、analyzer、`SPARSE_FLOAT_VECTOR` 和 `FunctionType.BM25` 一起设计。已经上线的 dense-only collection 要新增 BM25 时，通常创建新 collection 并通过 alias 切换。

## 输入输出协议

### 写入输入

```python
Document(
    id="doc-milvus-1",
    page_content="Milvus 使用 collection、schema 和 index 组织向量数据",
    metadata={
        "source": "milvus-guide",
        "chunk_no": 1,
        "vector": [0.05, 0.08, 0.91, ...],
    },
)
```

写入 Milvus 前会转换成包含 `id`、`text`、`source`、`chunk_no`、`vector` 的行数据。

### 检索输入

```python
query_vector = [0.05, 0.08, 0.90, ...]
filter_expr = 'source == "milvus-guide"'
limit = 3
output_fields = ["text", "source", "chunk_no"]
```

### 检索输出

```python
{
    "id": "doc-milvus-1",
    "score": 0.99,
    "text": "Milvus 使用 collection、schema 和 index 组织向量数据",
    "source": "milvus-guide",
    "chunk_no": 1,
}
```

生产环境可以在这个协议上继续增加：

- `tenant_id`：多租户隔离。
- `document_id`：文档级删除。
- `version`：索引版本或 schema 版本。
- `created_at` / `updated_at`：增量同步和排查。
- `acl`：权限过滤字段。

## 外部服务与配置

| 配置 | 默认值 | 用途 |
|------|--------|------|
| `MILVUS_URI` | `.milvus_tutorial/milvus_lite.db` | Milvus Lite 文件或 Standalone 地址 |
| `MILVUS_TOKEN` | 空字符串 | Standalone/Zilliz Cloud 认证 |
| `MILVUS_COLLECTION_PREFIX` | `learning_milvus` | 教程专用集合名前缀 |
| `MILVUS_DIMENSION` | `8` | 教学向量维度 |
| `MILVUS_TIMEOUT` | `8` | 单次连接或调用超时 |

## 从示例演进到生产代码

| 示例实现 | 生产替换 |
|----------|----------|
| 手写固定向量 | 替换为统一 embedding 服务 |
| `source` 字段过滤 | 扩展为租户、权限、版本、文档状态过滤 |
| `AUTOINDEX` | 根据数据规模和部署形态评估 HNSW、IVF、DiskANN 等索引 |
| 本地 `Milvus Lite` | 替换为 Milvus Standalone、Distributed 或 Zilliz Cloud |
| print 输出 | 替换为结构化日志、指标和 tracing |
| 示例级异常打印 | 替换为项目统一错误码和重试策略 |
