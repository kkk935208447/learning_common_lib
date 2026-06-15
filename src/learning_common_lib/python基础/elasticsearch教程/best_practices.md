# 最佳实践（best_practices）

本文汇总 Elasticsearch + Python 客户端的推荐做法，区分开发和生产环境，覆盖 mapping、查询、写入、分页、生命周期、性能和安全。所有结论都在本教程示例中验证过。

## 版本与连接

| 实践 | 说明 | 对应示例 |
|------|------|----------|
| 客户端大版本对齐服务端 | 8.x 服务端用 `elasticsearch>=8,<9`；混用会报 `media_type_header_exception` | `01_basics/01` |
| 客户端复用 | 应用生命周期内创建一次，关闭时释放；不要每请求新建 | `templates/client_factory.py` |
| 设置 `request_timeout` | 避免请求无限挂起；批量操作单独设更长超时 | 各示例 |
| 配 `retry_on_timeout` + `max_retries` | 应对瞬时网络抖动，配合幂等写入安全 | `templates/client_factory.py` |
| 配 `retry_on_status` | 常见只对 408/429/502/503/504 做退避重试；4xx 请求错误不要重试 | `templates/client_factory.py` |
| 开启 `http_compress` | 大响应或批量请求可减少网络传输，CPU 很紧张时再评估关闭 | `templates/client_factory.py` |
| 单次请求用 `client.options(...)` | 用 `ignore_status`、临时 `request_timeout` 覆盖默认值，不要污染全局客户端 | 多数示例 |
| 本地绕过代理 | `NO_PROXY`/`no_proxy` 包含 `127.0.0.1,localhost` | 各示例 `ensure_local_no_proxy` |

## mapping 与字段类型

| 实践 | 说明 |
|------|------|
| 检索文本用 `text` | 走分词，支持 `match` 全文检索 |
| 精确匹配/聚合/排序用 `keyword` | 不分词，整体值，支持 `term` 和 `terms` 聚合 |
| 既要检索又要聚合用 multi-field | `title` 为 text，`title.raw` 为 keyword |
| 显式定义 mapping | 关闭或谨慎用 dynamic mapping，避免类型被自动推断错 |
| 数值/日期用对应类型 | `integer`/`long`/`date`/`boolean`，别用 text 存数字 |
| mapping 视为不可变 | 字段类型定了改不了，变更走 reindex + alias |
| 用 index template 统一 | 生产中按索引名模式自动套用 mapping 和 settings |

**反例**：把分类、状态、ID 等精确值存成 `text`，结果 `term` 查不到、`terms` 聚合报 `fielddata` 错误。

## 查询

| 实践 | 说明 | 对应示例 |
|------|------|----------|
| 精确条件放 `filter` | 不算分、可缓存，比放 `must` 快 | `05_query_dsl/01` |
| 相关性匹配放 `must` | 参与评分，影响排序 | `05_query_dsl/01` |
| 排除用 `must_not` | 比应用层过滤高效 | `05_query_dsl/01` |
| 多字段检索用 `multi_match` | `best_fields` 取最佳字段，`^n` 加权 | `05_query_dsl/02` |
| 短语用 `match_phrase` | 要求词序相邻，`slop` 控制容忍度 | `05_query_dsl/02` |
| 容错用 `fuzziness: AUTO` | 处理拼写错误，但有性能代价，慎用 | `05_query_dsl/02` |
| 只要数量用 `count` | 比 `search` + 读 total 更轻 | `04_bulk/*` |
| 只要聚合用 `size=0` | 不返回命中文档，省序列化 | `06_aggregations/*` |
| 先用 `indices.validate_query` 验证 DSL | 复杂查询上线前先确认结构可执行，必要时开 `explain=True` | `roadmap.md` |
| 用 `explain` 排查单文档评分 | 看某个 `_id` 为什么命中、哪些子句贡献分数 | `05_query_dsl/02` |

## 写入

| 实践 | 说明 | 对应示例 |
|------|------|----------|
| 批量用 `helpers.bulk` | 比逐条 `index` 快几个数量级 | `04_bulk/01` |
| 大数据集用 `streaming_bulk` | 惰性生成器控制内存，逐条处理结果 | `04_bulk/02` |
| 单批控制在几 MB / 几千条 | 过大触发 429，过小浪费往返 | `04_bulk/02` |
| 配 `max_retries` + 退避 | 应对写入过载的瞬时 429 | `04_bulk/02` |
| 幂等写入用稳定 `_id` | `_id` 派生自业务主键，重跑不产生重复 | `03_crud/02` |
| 存在则更新用 `doc_as_upsert` | 一步完成 insert-or-update | `03_crud/02` |
| 计数累加用 `script` | 原子操作，避免读-改-写竞态 | `03_crud/02` |
| 慎用 `refresh="wait_for"` | 仅测试和强一致场景；高频写入会拖慢吞吐 | 各示例 |
| 长任务用 tasks 观察 | `reindex`、`update_by_query`、`delete_by_query` 可设 `wait_for_completion=False` 后轮询任务 | `11_advanced_search/05` |

## 分页

| 场景 | 推荐方案 | 说明 |
|------|----------|------|
| 前几页浅分页 | `from/size` | 简单，但 `from+size` 不能超过 `max_result_window`(默认 10000) |
| 深度翻页 / 全量导出 | `search_after` + PIT | 代价恒定，结果快照稳定 | 
| 离线批量遍历 | `helpers.scan` / `async_scan` | 内部基于 PIT/scroll，自动翻页 |

要点（见 `07_pagination/`）：
- `search_after` 的 sort 必须包含唯一字段（如加 `_shard_doc`），否则会漏或重。
- PIT 是有状态资源，`keep_alive` 到期前必须 `close_point_in_time`。
- PIT 锁定快照，翻页期间不反映新写入，这是特性不是 bug。

## 错误处理

| 实践 | 说明 | 对应示例 |
|------|------|----------|
| 区分异常类型 | `NotFoundError`(404)/`BadRequestError`(400)/`ConflictError`(409)，别统一 catch | `08_errors_recovery/01` |
| 可预期 404 用 `exists`/`ignore_status` | 避免用异常做正常控制流 | `08_errors_recovery/01` |
| 并发写用乐观并发控制 | `if_seq_no` + `if_primary_term`，冲突重读重试 | `08_errors_recovery/02` |
| bulk 用 `raise_on_error=False` | 收集单条错误而非整体抛出 | `04_bulk/01` |
| 区分 4xx 和 5xx | 4xx 是请求问题不该重试，5xx/超时可退避重试 | `08_errors_recovery/01` |

## 生命周期与生产化

| 实践 | 说明 | 对应示例 |
|------|------|----------|
| 应用读写 alias | 不绑定物理索引名，便于切换 | `09_production/01` |
| mapping 变更走 reindex + alias | create v2 → reindex → 原子切 alias → drop v1 | `09_production/01` |
| 长 reindex 用异步任务 | `wait_for_completion=False` 拿 task id，`tasks.get/list` 观察，必要时 `tasks.cancel` | `11_advanced_search/05` |
| 高并发用 `AsyncElasticsearch` | 配 `async with` 或显式 close，避免连接泄漏 | `09_production/02` |
| 异步也要限流 | 用 `asyncio.Semaphore` 控制并发，配超时和背压 | `09_production/02` |
| 索引生命周期用 ILM | 时序数据按大小/时间滚动、降冷、删除 | （超出本教程，生产建议） |

## 安全

| 实践 | 说明 |
|------|------|
| 生产必须开启认证 | API Key 或用户名密码，本教程无认证仅限本地学习 |
| 生产必须开启 TLS | `https://` + CA 证书校验 |
| 认证写法保持一种主线 | `api_key` 适合服务间调用；`basic_auth=(user, password)` 适合账号密码环境，别同时硬编码两套 |
| 校验证书 | 生产保留 `verify_certs=True`，通过 `ca_certs` 注入 CA；只在本地临时调试时考虑关闭 |
| 最小权限 | 应用账号只授予所需索引的读写权限 |
| 不在代码硬编码凭证 | 从环境变量或配置中心注入，见 `templates/settings.py` |
| 校验用户输入 | 不要把用户输入直接拼进 query，尤其是 script 查询 |

## 高级检索

| 实践 | 说明 | 对应示例 |
|------|------|----------|
| 大文档用 `_source` 过滤 | 只取需要的字段，降低网络和反序列化开销 | `11_advanced_search/01` |
| 命中展示用 `highlight` | 标签包裹匹配词；长文本设 `fragment_size` 控制片段 | `11_advanced_search/01` |
| 分组取代表用 `collapse` | 比聚合更适合直接拿文档；折叠字段须 keyword/数值 | `11_advanced_search/02` |
| 语义召回用 `dense_vector` + `knn` | `dims` 对齐 embedding 模型，`similarity` 匹配归一化方式 | `11_advanced_search/03` |
| 召回质量用混合检索 | 关键词 + 向量同时给出，用 `boost` 调两者权重 | `11_advanced_search/03` |
| 批量改删用 `*_by_query` | 比逐条往返高效；并发场景用 `conflicts="proceed"` | `11_advanced_search/04` |
| `num_candidates` 调召回 | 越大越准越慢，是 kNN 召回率和延迟的主要旋钮 | `11_advanced_search/03` |

## 索引与性能

| 实践 | 说明 | 对应示例 |
|------|------|----------|
| 单节点副本设 0 | 副本无处分配会让索引一直 yellow | `12_index_and_performance/01` |
| shard 数提前规划 | 创建后不可改；过多 shard 浪费资源，过少限制并行 | `12_index_and_performance/01` |
| 大批量导入关 refresh | 导入前 `refresh_interval=-1`，导入后恢复并手动 refresh | `12_index_and_performance/01` |
| 只读索引 force merge | `forcemerge(max_num_segments=1)` 合并 segment 提升查询；不要对写入中的索引用 | `12_index_and_performance/01` |
| 时序索引用 template | `put_index_template` 让按日期滚动的索引自动套 mapping | `12_index_and_performance/02` |
| 慢查询用 `profile` | 定位耗时在哪个 query 节点；有开销，排查时才开 | `12_index_and_performance/03` |
| 多查询用 `msearch` | 首页多组聚合/查询一次取回，减少往返 | `12_index_and_performance/03` |
| 先看 `cat.indices`/`indices.stats` | 排查文档数、store、segment、search/write 压力，不要只看应用日志 | `01_basics/01`、`roadmap.md` |

## 性能要点

- **filter 缓存**：重复的 filter 子句会被 ES 缓存到 bitset，比 query 快。
- **聚合下推**：把统计交给 ES 聚合，不要拉全量数据到应用层再算。
- **高基数聚合用 composite**：`terms` 默认只返回 top-10，高基数字段要用 composite aggregation 分页。
- **避免深度 from/size**：每个 shard 都要取 from+size 条再归并，代价随 from 线性增长。
- **批大小调优**：bulk 批大小没有万能值，按文档大小和集群配置压测得出。
- **单节点资源有限**：本教程在单节点 ES 上验证；密集连续请求可能触发 OOM，smoke 脚本特意在用例间留间隔。
