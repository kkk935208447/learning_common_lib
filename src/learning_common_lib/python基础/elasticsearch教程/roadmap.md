# Elasticsearch API 全景与学习路线

本文回答两个问题：真实工程里 Elasticsearch Python 客户端常按什么顺序调用，以及本教程每个示例覆盖哪些高频 API 和参数。建议先看 API 全景建立地图，再按阶段运行示例。

## 阅读方式与版本要求

- 本教程使用官方 `elasticsearch` Python 客户端，版本固定在 `>=8.19,<9`，需要与 Elasticsearch 8.x 服务端大版本对齐。
- 如果你已经熟悉搜索、RAG 或日志分析业务流程，重点看“工程使用流程”和“API 参数速查概览”；示例只补 Elasticsearch API 细节。
- 示例从当前目录运行：`UV_CACHE_DIR=/tmp/uv-cache uv run python examples/阶段目录/文件名.py`。

## API 全景

### Elasticsearch 工程使用流程

```text
连接自检:
Elasticsearch(hosts, api_key/basic_auth, request_timeout)
  -> ping()
  -> info()
  -> cluster.health()
  -> cat.indices() 查看当前索引清单

索引建模:
indices.create(index, settings, mappings, aliases)
  -> indices.get_mapping() / indices.get_settings()
  -> indices.analyze() 验证分词
  -> indices.validate_query() 验证 DSL 结构

写入与验证:
index() / update() / delete() / helpers.bulk()
  -> refresh="wait_for" 或 indices.refresh()
  -> get() / mget() / count() 验证数据

检索:
search(index, query, size, from_, sort, track_total_hits, source)
  -> highlight / collapse / aggs / knn 按需追加
  -> explain() 看单文档评分原因
  -> profile=True 看查询耗时分解

深分页与导出:
浅分页: search(from_, size)
深翻页: open_point_in_time() -> search(pit, search_after, sort) -> close_point_in_time()
离线遍历: helpers.scan() / async_scan()

索引发布与长任务:
create index_v2 -> reindex(wait_for_completion=False 可选)
  -> tasks.get() / tasks.list() 观察长任务
  -> update_aliases() 原子切换
  -> get_alias() 验证当前指向

运维排查:
cat.indices() / indices.stats()
  -> validate_query() / explain() / profile
  -> tasks.list() / tasks.get() / tasks.cancel()
```

### API 参数速查概览

| API/对象 | 常见参数 | 参数说明 | 主要示例 |
|----------|----------|----------|----------|
| `Elasticsearch(...)` / `AsyncElasticsearch(...)` | `hosts`、`api_key`、`basic_auth`、`request_timeout`、`max_retries`、`retry_on_timeout`、`retry_on_status`、`http_compress`、`verify_certs`、`ca_certs` | `hosts` 可是单地址或多节点；`api_key` 常用于 Elastic Cloud/生产服务；`basic_auth` 是用户名密码写法；`request_timeout` 限制单次请求；重试参数只适合可重试请求；TLS 生产必须校验证书 | `01_basics/01_connect_and_info.py`、`09_production/02_async_client.py`、`templates/client_factory.py` |
| `client.options(...)` | `ignore_status`、`request_timeout`、`api_key`、`basic_auth` | 对单次请求覆盖客户端默认选项；`ignore_status=404` 适合删除不存在索引这类可预期场景，不要吞掉未知错误 | 多数示例清理索引 |
| `indices.create(...)` | `index`、`settings`、`mappings`、`aliases`、`timeout`、`master_timeout` | 创建索引时一次性确定 shard、replica、analyzer、字段类型和初始 alias；字段类型后续不可随意修改 | `01_basics/02_index_and_search.py`、`02_mapping_analysis/`、`12_index_and_performance/02_index_template.py` |
| `mappings.properties` | `type`、`analyzer`、`fields`、`format`、`dims`、`index`、`similarity` | `text` 用于全文检索，`keyword` 用于过滤/聚合/排序；`fields` 建 multi-field；`dense_vector` 的 `dims/similarity` 要与 embedding 模型一致 | `02_mapping_analysis/01_field_types.py`、`11_advanced_search/03_knn_vector.py` |
| `indices.analyze(...)` | `index`、`analyzer`、`text`、`field` | 验证文本被如何切词，是排查“为什么查不到”的第一步 | `02_mapping_analysis/01_field_types.py`、`02_custom_analyzer.py` |
| `index(...)` / `create(...)` | `index`、`id`、`document`、`refresh`、`routing`、`op_type` | `index` 会覆盖同 ID 文档；`create` 只允许新建；`refresh="wait_for"` 便于测试立即可搜，但生产高频写入慎用 | `01_basics/02_index_and_search.py`、`03_crud/01_document_crud.py` |
| `get(...)` / `mget(...)` / `exists(...)` | `index`、`id`、`ids`、`docs`、`source`、`routing` | `get` 按 `_id` 取单文档；`mget` 批量按 ID 取；`exists` 做轻量存在性判断 | `03_crud/01_document_crud.py`；`mget` 作为常用 API 在文档中说明 |
| `update(...)` | `index`、`id`、`doc`、`doc_as_upsert`、`script`、`upsert`、`if_seq_no`、`if_primary_term`、`retry_on_conflict` | `doc` 是局部更新；`doc_as_upsert` 适合幂等写入；`script` 适合原子累加；乐观并发用 `_seq_no/_primary_term` | `03_crud/02_upsert_and_script.py`、`08_errors_recovery/02_optimistic_concurrency.py` |
| `helpers.bulk(...)` / `streaming_bulk(...)` / `async_bulk(...)` | `actions`、`chunk_size`、`max_retries`、`initial_backoff`、`max_backoff`、`raise_on_error`、`refresh`、`request_timeout` | `bulk` 一次返回汇总；`streaming_bulk` 逐条 yield，适合大数据；`raise_on_error=False` 后必须检查 errors | `04_bulk/`、`09_production/02_async_client.py` |
| `search(...)` | `index`、`query`、`size`、`from_`、`sort`、`track_total_hits`、`source`、`aggs`、`highlight`、`collapse`、`knn`、`pit`、`search_after`、`profile` | 核心检索入口；`query` 决定召回和评分；`source` 裁剪返回字段；`track_total_hits` 控制总数精确度；高级能力都挂在 search 上 | `05_query_dsl/`、`06_aggregations/`、`07_pagination/`、`11_advanced_search/` |
| Query DSL | `bool.must`、`filter`、`should`、`must_not`、`minimum_should_match`、`match.operator`、`fuzziness`、`match_phrase.slop`、`multi_match.fields/type` | `filter` 不算分且可缓存；`must` 参与评分；`fuzziness` 提高容错但有性能代价；字段加权用 `title^2` | `05_query_dsl/01_bool_query.py`、`02_full_text.py` |
| Aggregations | `size=0`、`aggs`、`terms.size`、`range.ranges`、`date_histogram.calendar_interval`、`avg`、`stats`、`cumulative_sum` | 聚合受 `query` 过滤；只要聚合时设 `size=0`；高基数分页聚合了解 `composite` | `06_aggregations/` |
| PIT / `search_after` | `open_point_in_time(index, keep_alive)`、`pit.id`、`search_after`、`sort`、`close_point_in_time(id)` | 深翻页用 PIT 固定快照；排序必须稳定；用完必须关闭 PIT | `07_pagination/02_search_after_pit.py` |
| `helpers.scan(...)` / `async_scan(...)` | `index`、`query`、`size`、`scroll`、`preserve_order` | 离线遍历或导出用，不适合作为用户分页接口；模板提供仓储封装 | `templates/sync_repository.py`、`templates/async_repository.py` |
| `reindex(...)` / alias API | `source`、`dest`、`refresh`、`wait_for_completion`、`slices`、`actions`、`alias` | mapping 变更走新索引 + reindex + alias 原子切换；长任务用 tasks API 观察 | `09_production/01_alias_reindex.py` |
| `update_by_query(...)` / `delete_by_query(...)` | `index`、`query`、`script`、`conflicts`、`refresh`、`wait_for_completion`、`slices` | 按条件批量改删，重操作；并发冲突用 `conflicts="proceed"` 后要检查冲突数 | `11_advanced_search/04_by_query_ops.py`、`05_tasks_long_running.py` |
| `tasks.get/list/cancel(...)` | `task_id`、`actions`、`detailed`、`wait_for_completion`、`timeout` | 观察 `reindex`、`update_by_query`、`delete_by_query` 这类长任务；生产可按任务 ID 轮询或取消 | `11_advanced_search/05_tasks_long_running.py` |
| 排查类 API | `cluster.health`、`cat.indices`、`indices.stats`、`count`、`indices.validate_query`、`explain`、`profile=True`、`msearch` | 类似 ES 里的 ping、表清单、统计、SQL `EXPLAIN`；用于连接验证、DSL 验证、评分/性能排查 | `01_basics/01_connect_and_info.py`、`05_query_dsl/02_full_text.py`、`12_index_and_performance/03_profile_msearch.py` |

### 客户端与连接

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `Elasticsearch(...)` | `hosts`、`cloud_id`、`api_key`、`basic_auth`、`request_timeout`、`max_retries`、`retry_on_timeout`、`retry_on_status`、`http_compress`、`verify_certs`、`ca_certs` | 同步客户端；适合脚本、离线导入、同步 Web 服务和管理任务 | 阶段一、模板 |
| `AsyncElasticsearch(...)` | 同同步客户端，另配合 `async with` 或 `await close()` | 异步客户端；适合 FastAPI、异步 worker 和并发检索 | 阶段九 |
| `client.options(...)` | `ignore_status`、`request_timeout`、`api_key`、`basic_auth` | 单次请求覆盖默认连接选项；适合清理索引、长请求或临时认证切换 | 阶段八、模板 |
| `ping()` / `info()` / `cluster.health()` | `request_timeout`、`timeout`、`master_timeout` | 连接自检、版本确认、集群健康检查 | 阶段一 |

参数要点：

- `hosts` 可以是单地址或多个节点地址；Elastic Cloud 常用 `cloud_id`。
- `api_key` 适合云服务和生产自动化；`basic_auth=(user, password)` 是用户名密码写法，模板已支持两者，API Key 优先。
- `request_timeout` 建议在客户端默认值和长任务请求上显式设置，避免请求无限等待。
- `retry_on_timeout`、`max_retries`、`retry_on_status` 只适合幂等或可重试请求；写请求重试前要确认主键幂等。
- `verify_certs` 和 `ca_certs` 是 TLS 生产边界；本地调试可以放宽，生产不应关闭证书校验。
- 本地代理可能影响 `localhost:9200`，示例会处理 `NO_PROXY/no_proxy`。

### 索引、mapping 与 analyzer

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `indices.create(...)` | `index`、`settings`、`mappings`、`aliases`、`timeout`、`master_timeout` | 创建索引；一次性确定分片、副本、分词器、字段类型和初始别名 | 阶段一、二、十二 |
| `indices.exists(...)` / `indices.delete(...)` | `index`、`ignore_unavailable`、`allow_no_indices`、`timeout` | 判断索引是否存在和清理教程索引 | 多数示例 |
| `indices.get_mapping(...)` / `indices.get_settings(...)` | `index`、`name`、`flat_settings` | 查看字段和索引配置，类似关系型数据库的 `DESC table` 和配置查看 | 阶段二、十二 |
| `indices.put_settings(...)` | `index`、`settings` | 调整可动态修改的索引设置，例如副本数、刷新间隔 | 阶段十二 |
| `indices.analyze(...)` | `index`、`analyzer`、`field`、`text` | 查看文本如何分词，排查全文检索命中问题 | 阶段二 |
| `indices.put_index_template(...)` | `name`、`index_patterns`、`template`、`priority` | 给一类新索引统一套用 settings、mapping 和 alias | 阶段十二 |

参数要点：

- `settings.number_of_shards` 创建后不能直接修改；生产变更通常走新索引 + reindex + alias。
- 单节点本地环境建议 `number_of_replicas=0`，否则集群健康可能长期是 yellow。
- `refresh_interval` 影响写入可见性和吞吐；批量导入可临时调大或设 `-1`，导入后恢复。
- `mappings.properties.type` 是字段协议核心：`text` 用于全文检索，`keyword` 用于过滤、聚合、排序。
- `fields` 用于 multi-field，例如同一字段既有 `text` 检索又有 `.raw` 精确聚合。
- `dense_vector.dims/index/similarity` 必须和 embedding 模型、检索方式一致。
- analyzer 是创建期设计；中文分词通常需要插件或专门 analyzer，不要默认 standard analyzer 能处理所有中文场景。

### 文档写入、读取与批量

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `index(...)` / `create(...)` | `index`、`id`、`document`、`refresh`、`routing`、`op_type` | 单文档写入；`index` 可覆盖，`create` 只允许新增 | 阶段一、三 |
| `get(...)` / `mget(...)` / `exists(...)` | `index`、`id`、`ids`、`docs`、`source`、`routing` | 按 `_id` 读取或判断存在；`mget` 减少多次网络往返 | 阶段三 |
| `update(...)` | `index`、`id`、`doc`、`doc_as_upsert`、`script`、`upsert`、`if_seq_no`、`if_primary_term`、`retry_on_conflict` | 局部更新、幂等 upsert、原子脚本更新和乐观并发控制 | 阶段三、八 |
| `delete(...)` | `index`、`id`、`refresh`、`routing` | 删除单文档；测试可配合 refresh 验证 | 阶段三 |
| `helpers.bulk(...)` / `streaming_bulk(...)` | `actions`、`chunk_size`、`max_chunk_bytes`、`max_retries`、`initial_backoff`、`max_backoff`、`raise_on_error`、`request_timeout` | 批量写入；`streaming_bulk` 可逐条观察成功或失败 | 阶段四 |

参数要点：

- `id` 是幂等写入的关键；导入任务可重跑时不要依赖随机 ID。
- `refresh="wait_for"` 便于测试立即搜索到数据，生产高频写入应慎用。
- `doc_as_upsert=True` 适合“有则更新、无则创建”的轻量场景；复杂初始化用 `script + upsert`。
- `if_seq_no/if_primary_term` 是乐观锁边界，能避免旧版本覆盖新版本。
- bulk action 要明确 `_op_type`、`_index`、`_id` 和 `_source`，批量失败时必须检查 errors 或逐条结果。
- `chunk_size`、`max_retries`、`initial_backoff`、`max_backoff` 是导入稳定性参数，吞吐调优要结合 429 和集群压力观察。

### 检索、Query DSL 与聚合

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `search(...)` | `index`、`query`、`size`、`from_`、`sort`、`track_total_hits`、`source`、`aggs`、`highlight`、`collapse`、`knn`、`pit`、`search_after`、`profile` | 核心检索入口；全文、过滤、聚合、向量和诊断能力都挂在这里 | 阶段五到十二 |
| Query DSL | `bool.must`、`filter`、`should`、`must_not`、`minimum_should_match`、`match.operator`、`fuzziness`、`multi_match.fields/type` | 描述召回、过滤、评分和字段加权 | 阶段五 |
| Aggregations | `aggs`、`terms.size`、`range.ranges`、`date_histogram.calendar_interval`、`avg`、`stats`、`cumulative_sum` | 分桶统计、指标统计、时间序列和管道聚合 | 阶段六 |
| `count(...)` | `index`、`query` | 只取数量，不返回命中文档 | 阶段三、排查 |
| `indices.validate_query(...)` / `explain(...)` | `query`、`explain`、`id` | 验证 DSL 是否可执行，解释单文档为什么命中和如何算分 | 阶段五、排查 |
| `msearch(...)` | `searches`、`index` | 一次请求合并多组搜索，减少网络往返 | 阶段十二 |

参数要点：

- `bool.filter` 不算分且更适合精确条件；`bool.must` 参与评分。
- `match.operator` 决定分词后是 OR 还是 AND；`fuzziness` 提高容错但会增加查询成本。
- `multi_match.fields` 支持 `title^2` 这类字段加权；权重需要用真实样本评测。
- `source` 或 `_source` includes/excludes 控制返回字段，避免把大字段全部传回服务端调用方。
- `track_total_hits` 控制总命中数精确度；列表页未必需要精确总数。
- 只看聚合时设置 `size=0`，减少无用命中文档传输。
- `profile=True` 只用于排查慢查询，不应在常规线上请求长期打开。

### 分页、导出与遍历

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `search(from_, size, sort)` | `from_`、`size`、`sort`、`track_total_hits` | 浅分页，适合用户前几页列表 | 阶段七 |
| `open_point_in_time(...)` | `index`、`keep_alive` | 打开 PIT 快照，让多页查询看到一致视图 | 阶段七 |
| `search(pit, search_after, sort)` | `pit.id`、`pit.keep_alive`、`search_after`、`sort`、`size` | 深翻页，避免 `from/size` 深分页代价 | 阶段七 |
| `close_point_in_time(...)` | `id` | 释放 PIT 资源 | 阶段七 |
| `helpers.scan(...)` / `async_scan(...)` | `index`、`query`、`size`、`scroll`、`preserve_order` | 离线遍历、导出和后台任务消费 | 模板 |

参数要点：

- `from/size` 是浅分页方案，默认受 `index.max_result_window=10000` 限制。
- `sort` 必须稳定，深翻页建议包含唯一字段作为兜底排序。
- PIT 的 `keep_alive` 只设置够下一页使用的时间；每次 search 可续期，但用完必须 close。
- `helpers.scan` 适合离线遍历，不适合作为用户分页接口。
- `preserve_order=True` 会保留排序但牺牲 scan 性能，只在确实需要顺序时使用。

### 高级检索与向量

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `search(highlight=...)` | `fields`、`pre_tags`、`post_tags`、`fragment_size`、`number_of_fragments` | 返回命中片段，服务检索结果页展示 | 阶段十一 |
| `search(collapse=...)` | `field`、`inner_hits`、`max_concurrent_group_searches` | 按字段折叠去重，例如每个商品或文档只展示代表命中 | 阶段十一 |
| `dense_vector` mapping | `dims`、`index`、`similarity` | 存储向量字段并启用近似向量检索 | 阶段十一 |
| `search(knn=...)` | `field`、`query_vector`、`k`、`num_candidates`、`boost`、`filter` | kNN 向量召回，可与关键词查询混合 | 阶段十一 |
| `elasticsearch.dsl` | `Document`、`Search`、`Q`、`Index`、`to_dict()` | 用对象方式定义 mapping 和组合查询，最终仍落到底层 client API | 阶段十 |

参数要点：

- highlight 会增加返回体积和查询开销，字段和片段数要收敛。
- `_source` 裁剪通常要和 highlight 一起设计，避免结果页传回不需要的大字段。
- collapse 字段应是 `keyword` 或数值等可排序/聚合字段，不适合直接用 `text`。
- `inner_hits` 能取组内更多命中，但会放大查询成本。
- kNN 的 `dims` 必须和 embedding 维度一致；`similarity` 要与向量归一化方式匹配。
- `num_candidates` 越大召回通常越好、延迟越高；关键词 + 向量混合权重需要离线评测。

### 发布、长任务与运维排查

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `reindex(...)` | `source`、`dest`、`query`、`script`、`refresh`、`wait_for_completion`、`slices`、`requests_per_second` | 把旧索引数据迁移到新索引，常用于 mapping 变更 | 阶段九、十一 |
| `indices.update_aliases(...)` / `indices.get_alias(...)` | `actions`、`name`、`index` | 原子切换读写入口，支持蓝绿发布和回滚 | 阶段九 |
| `update_by_query(...)` / `delete_by_query(...)` | `index`、`query`、`script`、`conflicts`、`refresh`、`wait_for_completion`、`slices` | 按条件批量维护数据 | 阶段十一 |
| `tasks.get(...)` / `tasks.list(...)` / `tasks.cancel(...)` | `task_id`、`actions`、`detailed`、`wait_for_completion`、`timeout` | 观察、轮询或取消长任务 | 阶段十一 |
| `cat.indices(...)` / `indices.stats(...)` | `index`、`format`、`h`、`s`、`metric` | 查看索引清单、文档数、存储、搜索和写入统计 | 阶段一、排查 |
| `indices.forcemerge(...)` | `index`、`max_num_segments`、`request_timeout` | 合并 segment；通常只对导入完成且接近只读的索引使用 | 阶段十二 |

参数要点：

- mapping 变更不要在线硬改旧索引，主线是新索引建模、reindex、alias 原子切换。
- `wait_for_completion=False` 只表示任务已提交，不代表迁移或批量修改已经完成。
- 长任务提交后要保存 `task_id`，用 `tasks.get` 轮询完成状态并检查失败、冲突和计数。
- `conflicts="proceed"` 会跳过版本冲突，不是无损成功；结果里的冲突数必须进入日志或告警。
- `slices` 可并行加速 by-query/reindex，但会增加集群压力。
- `forcemerge` 成本高，通常只对不会继续频繁写入的索引做。

### 管理与排查 API 了解项

| API/对象 | 常用参数 | 作用 | 本教程处理方式 |
|----------|----------|------|----------------|
| `cat.indices(...)` | `index`、`format`、`h`、`s` | 列出索引清单、文档数、存储大小，类似关系型数据库里看表 | 连接示例输出教程索引清单 |
| `indices.stats(...)` | `index`、`metric` | 查看索引写入、搜索、segment、store 等统计 | 在文档中说明，生产排查时使用 |
| `indices.validate_query(...)` | `index`、`query`、`explain` | 验证 Query DSL 是否可执行，可输出解释 | 在 roadmap/best practices 中作为排查 API |
| `explain(...)` | `index`、`id`、`query` | 查看某个文档为什么命中、分数如何组成 | 全文检索示例演示 |
| `mget(...)` | `index`、`ids`、`docs`、`source` | 批量按 `_id` 取文档，减少多次往返 | 文档说明为常用 CRUD API，不单独成章 |
| `ingest.put_pipeline(...)` | `id`、`processors`、`description` | 写入前做字段处理、清洗、解析 | 属于数据接入专题，本教程只提醒存在 |
| `snapshot.*` / `security.*` / ILM | repository、policy、role、api key | 备份、安全、生命周期治理 | 属于集群治理专题，不纳入主线示例 |

## 学习路线总览

学习主线：**连接 → 建模 → 写入 → 检索 → 分析 → 翻页 → 容错 → 生产化 → 高级检索 → 性能排查**。前面建立 API 心智模型，后面解决真实工程问题。

| 阶段 | 主题 | 你会学到 |
|------|------|----------|
| 1 | 连接与最小闭环 | `Elasticsearch`、`ping`、`info`、`cluster.health`、`cat.indices`、版本对齐 |
| 2 | mapping 与分析器 | `text`/`keyword`、`indices.analyze`、自定义 analyzer、multi-field |
| 3 | 文档 CRUD | `index`、`get`、`update`、`delete`、`exists`、`doc_as_upsert`、script 累加 |
| 4 | 批量写入 | `helpers.bulk`、`streaming_bulk`、错误收集、429 退避 |
| 5 | Query DSL | `bool`、`match`、`match_phrase`、`multi_match`、`explain` |
| 6 | 聚合 | `terms`、`range`、`stats`、`date_histogram`、`cumulative_sum` |
| 7 | 分页 | `from/size`、`track_total_hits`、`search_after` + PIT |
| 8 | 错误与恢复 | 异常类型、`ignore_status`、`if_seq_no/if_primary_term` |
| 9 | 生产实践 | alias + reindex 零停机切换、`AsyncElasticsearch` 并发 |
| 10 | 高级 DSL | `elasticsearch.dsl` 的 `Document`、`Search`、`Q` |
| 11 | 高级检索与长任务 | `highlight`、`collapse`、`knn`、`*_by_query`、`tasks` |
| 12 | 索引与性能 | shard/replica/`refresh_interval`、index template、`profile`、`msearch` |

## 学习阶段详解

### 阶段一：连接与最小闭环（01_basics/）

**学什么**：创建客户端、确认版本对齐、查看集群健康、跑通 index → refresh → search → delete。

**为什么在这里**：一切都从能连上开始。版本对齐和本地代理是 Elasticsearch Python 客户端最容易踩的前置坑。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 1 | `01_connect_and_info.py` | `Elasticsearch`、`ping`、`info`、`cluster.health`、`cat.indices` | 客户端大版本与服务端是否一致，集群状态 green/yellow，当前教程索引清单 |
| 2 | `02_index_and_search.py` | `indices.create`、`index`、`indices.refresh`、`search`、`indices.delete` | refresh 后文档立即可搜，命中评分 |

**关键收获**：能连上 ES，能完成一次完整写入和检索，理解 refresh 带来的可见性延迟。

### 阶段二：mapping 与分析器（02_mapping_analysis/）

**学什么**：`text` 与 `keyword` 的本质差别、分词如何影响检索、自定义 analyzer 和 multi-field。

**为什么在这里**：字段类型选错是“查不到”和“聚合报错”的头号根因，必须在写大量数据前理解。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 3 | `01_field_types.py` | `text`/`keyword`、`term` vs `match`、`indices.analyze` | 同一份值在 text 和 keyword 下的命中差异，分词结果 |
| 4 | `02_custom_analyzer.py` | 自定义 analyzer、`char_filter`、multi-field `.raw` | HTML 被剥离、停用词被去掉，`.raw` 用于精确聚合 |

**关键收获**：能根据“要检索还是要精确匹配/聚合”正确选择字段类型，能定制分词流程。

### 阶段三：文档 CRUD（03_crud/）

**学什么**：单文档增删改查、局部更新、幂等写入和原子累加。

**为什么在这里**：检索之前要先有数据。理解 update 是“读-改-写”而非普通字段赋值，是写并发安全代码的前提。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 5 | `01_document_crud.py` | `index`、`get`、`update(doc)`、`delete`、`exists` | 部分更新只改传入字段，version 递增 |
| 6 | `02_upsert_and_script.py` | `doc_as_upsert`、`script` + `upsert` | upsert 重复执行不重复建新文档，script 原子 +1 |

**关键收获**：能写出可重复执行的幂等写入，能用 script 做并发安全的计数更新。

### 阶段四：批量写入（04_bulk/）

**学什么**：用 `helpers.bulk` 和 `streaming_bulk` 高效批量写入，处理部分失败和限流。

**为什么在这里**：真实导入从来不是一条条写。批量是性能关键，也是错误处理难点。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 7 | `01_bulk_helpers.py` | `helpers.bulk`、action 结构、`raise_on_error` | 一条非法文档被收集到 errors 而不中断整体 |
| 8 | `02_streaming_bulk.py` | `streaming_bulk`、`chunk_size`、`max_retries`、退避 | 逐条 yield 结果，惰性生成器控制内存 |

**关键收获**：能批量导入大数据集，能区分整体失败和单条失败，能配置 429 退避重试。

### 阶段五：Query DSL（05_query_dsl/）

**学什么**：bool 复合查询、全文检索 match 家族、相关性评分和 `explain`。

**为什么在这里**：这是 Elasticsearch 的核心能力。query/filter 上下文直接决定性能和评分行为。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 9 | `01_bool_query.py` | `bool`(must/filter/should/must_not)、`minimum_should_match` | filter 不算分，must_not 排除，should 影响排序 |
| 10 | `02_full_text.py` | `match`、`match_phrase`、`multi_match`、`explain` | OR/AND 区别，短语相邻要求，跨字段加权评分，单文档评分解释 |

**关键收获**：能组合复杂查询条件，能区分精确过滤和全文匹配，能用解释 API 排查评分。

### 阶段六：聚合（06_aggregations/）

**学什么**：桶聚合、指标聚合、嵌套子聚合、时间序列和管道聚合。

**为什么在这里**：Elasticsearch 不只是搜索引擎，也是实时分析引擎。聚合是日志分析和数据看板的基础。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 11 | `01_metrics_and_buckets.py` | `terms`、`range`、`stats`、`avg`、`size=0` | 分桶 + 桶内指标，`size=0` 只要聚合不要命中 |
| 12 | `02_pipeline_and_date.py` | `date_histogram`、`cumulative_sum`、query + aggs | 聚合受 query 过滤，管道聚合基于已有桶二次计算 |

**关键收获**：能做分组统计和区间分布，能做时间序列分析和累计计算。

### 阶段七：分页（07_pagination/）

**学什么**：`from/size` 浅分页的代价和上限，`search_after` + PIT 的深翻页。

**为什么在这里**：分页是每个列表接口都要面对的问题。深翻页用错方式会拖垮集群。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 13 | `01_from_size.py` | `from_`、`size`、`sort`、`track_total_hits`、`max_result_window` | `from=10000` 触发上限错误 |
| 14 | `02_search_after_pit.py` | `open_point_in_time`、`search_after`、`close_point_in_time` | PIT 锁定快照，按 sort 值翻页无重无漏，用完必须 close |

**关键收获**：能为浅分页和深度遍历选对方案，理解 PIT 是有状态资源必须释放。

### 阶段八：错误与恢复（08_errors_recovery/）

**学什么**：客户端异常类型的区分处理，乐观并发控制处理写冲突。

**为什么在这里**：生产代码必须能区分 404/400/409/5xx，而不是统一 catch。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 15 | `01_exception_types.py` | `NotFoundError`、`BadRequestError`、`ConflictError`、`ignore_status` | 用 exists/ignore_status 处理可预期 404，区分 4xx/5xx |
| 16 | `02_optimistic_concurrency.py` | `if_seq_no`、`if_primary_term`、`ConflictError` | 过期版本写入触发 409，重读后重试成功 |

**关键收获**：能写出可区分处理的错误恢复代码，能用乐观锁安全处理并发更新。

### 阶段九：生产实践（09_production/）

**学什么**：alias + reindex 实现零停机 mapping 变更，异步客户端并发检索。

**为什么在这里**：mapping 不可变是硬约束，线上变更必须有零停机方案；高并发服务需要异步客户端。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 17 | `01_alias_reindex.py` | `update_aliases`、`reindex`、蓝绿切换 | 应用始终查 alias，底层 v1→v2 原子切换不中断 |
| 18 | `02_async_client.py` | `AsyncElasticsearch`、`async with`、`asyncio.gather`、`async_bulk` | 并发查询，`async with` 自动关闭连接 |

**关键收获**：能设计索引版本切换流程，能把同步代码迁移到异步服务而不泄漏连接。

### 阶段十：高级 DSL（10_dsl/）

**学什么**：用 `elasticsearch.dsl` 以面向对象方式建模文档和构建查询。

**为什么在这里**：复杂查询用 dict 写难维护。DSL 提升可读性和复用性，但与底层 client 等价，放后面便于对照理解。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 19 | `01_document_orm.py` | `Document`、`Search`、`Q`、`to_dict` | 类声明 mapping，链式构建查询，`to_dict` 看等价底层 DSL |

**关键收获**：能看懂并使用 DSL 高级 API，能在 dict 和 DSL 之间互转排查问题。

### 阶段十一：高级检索与长任务（11_advanced_search/）

**学什么**：高亮、字段裁剪、折叠去重、向量 kNN、按条件批量改删和长任务观察。

**为什么在这里**：基础检索跑通后，真实检索产品还需要命中展示、返回体积控制、业务去重、语义召回和批量维护。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 20 | `01_highlight_source.py` | `highlight`、`pre_tags`、`_source` includes/excludes | 命中词被标签包裹，返回字段被裁剪 |
| 21 | `02_collapse_dedup.py` | `collapse`、`inner_hits` | 每个分组只返回代表文档，`inner_hits` 取组内更多 |
| 22 | `03_knn_vector.py` | `dense_vector`、`knn`、关键词 + 向量混合 | 向量相似度召回，混合检索合并两种得分 |
| 23 | `04_by_query_ops.py` | `update_by_query`、`delete_by_query`、`conflicts="proceed"` | 按条件批量改/删，打印受影响文档数 |
| 24 | `05_tasks_long_running.py` | `wait_for_completion=False`、`tasks.get`、`tasks.list` | 长任务拿到 task id，轮询任务状态和最终响应 |

**关键收获**：能做出有高亮、去重、语义召回的检索体验，能安全观察批量维护任务。

### 阶段十二：索引与性能（12_index_and_performance/）

**学什么**：分片/副本/刷新间隔等索引设置、批量导入调优、索引模板、慢查询剖析和请求合并。

**为什么在这里**：检索能力齐备后，要让它在真实数据量下跑得快、可运维。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 25 | `01_index_settings.py` | `number_of_shards/replicas`、`refresh_interval`、`forcemerge` | 导入前关 refresh、导入后恢复并 force merge 的调优套路 |
| 26 | `02_index_template.py` | `put_index_template`、`index_patterns`、`priority` | 匹配命名的新索引自动套用 mapping/settings |
| 27 | `03_profile_msearch.py` | `profile=True`、`msearch` | 查询耗时分解定位慢点，一次请求取回多组结果 |

**关键收获**：能为写入和查询做基本调优，能用模板统一时序索引族，能用 profile/msearch 排查和减少往返。

## 模板与后续阅读

阅读 `templates/`：

1. `settings.py`：统一连接配置和索引命名。
2. `client_factory.py`：同步/异步客户端工厂，注入超时、重试和认证。
3. `sync_repository.py`：同步脚本/离线任务的仓储骨架。
4. `async_repository.py`：异步服务/worker 的仓储骨架。

本教程不展开的生产专题：ILM/data stream、snapshot、security/RBAC、ingest pipeline、ES|QL、跨集群检索。它们属于集群治理或数据平台专项，建议在掌握本路线后按官方文档单独学习。
