# 架构映射（architecture_map）

本文把教程的知识点映射到真实检索工程的分层和运行链路，说明从示例代码演进到生产代码时哪些部分需要替换、封装或下沉。

## 知识点到工程分层

```text
┌─────────────────────────────────────────────────────────────┐
│ 应用层 (API / Worker / 脚本)                                   │
│   读写 alias，不绑定物理索引名                                  │
│   FastAPI 路由、Celery/taskiq worker、离线导入脚本             │
├─────────────────────────────────────────────────────────────┤
│ 仓储层 (Repository)            ← templates/sync_repository.py  │
│   封装 index/get/search/bulk/scan，统一异常透传                │
│                                  templates/async_repository.py │
├─────────────────────────────────────────────────────────────┤
│ 客户端层 (Client)              ← templates/client_factory.py   │
│   超时、重试、认证、连接池；应用生命周期内复用，不每请求新建    │
├─────────────────────────────────────────────────────────────┤
│ 配置层 (Settings)              ← templates/settings.py         │
│   host、api_key、index_prefix、timeout；索引命名规则           │
├─────────────────────────────────────────────────────────────┤
│ Elasticsearch 集群                                             │
│   index → shard → segment；mapping、analyzer、alias           │
└─────────────────────────────────────────────────────────────┘
```

| 教程阶段 | 工程位置 | 生产演进 |
|----------|----------|----------|
| 01 连接 | 客户端层 | 单 host 改为多 host 列表 + sniff_on_start，注入 TLS 和 API Key |
| 02 mapping | 索引设计 | mapping 纳入版本管理，用 index template / component template 统一 |
| 03 CRUD | 仓储层 | 封装为领域方法，幂等写入用 `_id` 派生自业务主键 |
| 04 bulk | 数据管道 | 接入消息队列或 Logstash/Beats，批大小和退避按吞吐调优 |
| 05 Query DSL | 检索服务 | 查询模板化，filter 子句缓存，按业务拆查询构建器 |
| 06 聚合 | 分析/看板 | 聚合下推到 ES，避免应用层拉全量再统计；高基数用 composite |
| 07 分页 | 列表接口 | 浅分页用 from/size，深遍历/导出用 search_after + PIT |
| 08 容错 | 全链路 | 异常分类映射为 HTTP 状态码或重试策略，乐观锁保护并发写 |
| 09 生产 | 发布流程 | alias 切换纳入 CI/CD，异步客户端接入服务生命周期 |
| 10 DSL | 检索服务 | 复杂查询用 DSL 提升可维护性，与 dict 互转便于调试 |

## 检索请求的运行链路

```text
用户查询
  → 应用构建 query DSL（match/bool/filter）
  → 客户端序列化为 HTTP 请求（带版本协商头）
  → 协调节点接收，分发到各 shard
  → 每个 shard 本地执行：倒排索引匹配 → 打分 → 取 top-K
  → 协调节点归并各 shard 结果，全局排序
  → 返回 hits + aggregations
应用解析 hits（_id / _score / _source）
```

**教学映射**：
- `05_query_dsl/` 对应“构建 query DSL”和“打分”环节。
- `06_aggregations/` 对应 shard 本地聚合 + 协调节点归并。
- `07_pagination/` 的 `from/size` 代价正源于“每个 shard 都要取 from+size 条”再归并。
- `search_after + PIT` 用快照固定 segment，避免翻页期间 segment 合并导致的漂移。
- `11_advanced_search/` 的 kNN 在 HNSW 图索引上做近似最近邻；混合检索在协调节点合并关键词与向量两路得分。
- `12_index_and_performance/` 的 profile 暴露的正是各 shard 本地执行阶段的耗时分解。

## 写入链路与可见性

```text
index / bulk 请求
  → 写入对应 shard 的 translog + in-memory buffer
  → refresh（默认 1s 或手动）生成新 segment → 文档变得可搜
  → flush 把 segment 持久化，清空 translog
  → 副本同步
```

**教学映射**：
- `01_basics` 和各示例里的 `refresh="wait_for"` / `indices.refresh` 对应“refresh 生成 segment”，这是“写完立刻搜不到”的根因。
- `04_bulk/` 的批大小直接影响 translog 和 segment 压力，过大触发 429。
- `08_errors_recovery/02` 的 `_seq_no`/`_primary_term` 来自写入链路的版本元数据。

## 索引生命周期与零停机变更

```text
应用 ──读写──> alias ──指向──> index_v1 (mapping A)

需求变更（mapping 不可变）：
  1. create index_v2 (mapping B)
  2. reindex index_v1 → index_v2
  3. update_aliases 原子地 {remove v1, add v2}
  4. 应用无感知切换到 index_v2
  5. 确认无误后 drop index_v1
```

**教学映射**：`09_production/01_alias_reindex.py` 完整演示了这条链路。生产中第 2 步常用 `reindex` 的 `slices` 并行化，第 3 步的原子性是零停机的关键。

## 从示例到生产的替换清单

| 示例做法 | 生产做法 |
|----------|----------|
| `Elasticsearch("http://localhost:9200")` 无认证 | 多节点 + TLS + API Key，从配置中心注入 |
| 每个示例新建客户端 | 应用启动时创建单例客户端，关闭时释放 |
| 直接 `indices.create` 写死 mapping | index template + 版本化 mapping 文件 |
| `refresh="wait_for"` 保证立即可见 | 仅测试用；生产靠默认 refresh，按延迟需求调 `refresh_interval` |
| 查询条件硬编码 dict | 查询构建器 / DSL，filter 复用与缓存 |
| 示例内 `try/finally` 删索引清理 | 教学专用；生产数据持久，用 ILM 管理生命周期 |
| 同步 `Elasticsearch` | 高并发 Web 服务用 `AsyncElasticsearch` + 连接池上限 |
