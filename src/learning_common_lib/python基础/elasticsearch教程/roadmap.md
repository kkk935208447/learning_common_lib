# 学习路线（roadmap）

本文回答“应该按什么顺序学 Elasticsearch 教程、每个文件学什么、为什么放在这里”。建议严格按阶段顺序运行，每个示例都能独立执行并自动清理。

学习主线：**连接 → 建模 → 写入 → 检索 → 分析 → 翻页 → 容错 → 生产化 → 高级抽象**。前面建立心智模型，后面解决真实工程问题。

## 阶段一：连接与最小闭环（01_basics/）

**学什么**：创建客户端、确认版本对齐、跑通 index → refresh → search → delete。

**为什么在这里**：一切都从一个能用的连接开始。版本对齐是 Elasticsearch 客户端最容易踩的第一个坑，必须先讲清。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 1 | `01_connect_and_info.py` | `Elasticsearch`、`ping`、`info`、`cluster.health` | 客户端大版本与服务端是否一致，集群状态 green/yellow |
| 2 | `02_index_and_search.py` | `indices.create`、`index`、`refresh`、`search` | refresh 后文档立即可搜，命中评分 |

**关键收获**：能连上 ES，能完成一次完整的写入和检索，理解 refresh 带来的可见性延迟。

## 阶段二：mapping 与分析器（02_mapping_analysis/）

**学什么**：`text` 与 `keyword` 的本质差别、分词如何影响检索、自定义 analyzer 和 multi-field。

**为什么在这里**：字段类型选错是“查不到”和“聚合报错”的头号根因，必须在写大量数据前理解。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 3 | `01_field_types.py` | `text`/`keyword`、`term` vs `match`、`indices.analyze` | 同一份值在 text 和 keyword 下的命中差异，分词结果 |
| 4 | `02_custom_analyzer.py` | 自定义 analyzer、`char_filter`、multi-field `.raw` | html 被剥离、停用词被去掉，`.raw` 用于精确聚合 |

**关键收获**：能根据“要检索还是要精确匹配/聚合”正确选择字段类型，能定制分词流程。

## 阶段三：文档 CRUD（03_crud/）

**学什么**：单文档的增删改查，部分更新，以及幂等写入和原子累加。

**为什么在这里**：检索之前要先有数据。理解 update 是“读-改-写”而非原子字段操作，是写并发安全代码的前提。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 5 | `01_document_crud.py` | `index`、`get`、`update(doc)`、`delete`、`exists` | 部分更新只改传入字段，version 递增 |
| 6 | `02_upsert_and_script.py` | `doc_as_upsert`、`script` + `upsert` | upsert 重复执行不重复累加，script 原子 +1 |

**关键收获**：能写出可重复执行的幂等写入，能用 script 做并发安全的计数更新。

## 阶段四：批量写入（04_bulk/）

**学什么**：用 `helpers.bulk` 和 `streaming_bulk` 高效批量写入，处理部分失败和限流。

**为什么在这里**：真实数据导入从来不是一条条写。批量是性能关键，也是错误处理的难点。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 7 | `01_bulk_helpers.py` | `helpers.bulk`、action 结构、`raise_on_error` | 一条非法文档被收集到 errors 而不中断整体 |
| 8 | `02_streaming_bulk.py` | `streaming_bulk`、`chunk_size`、`max_retries`、退避 | 逐条 yield 结果，惰性生成器控制内存 |

**关键收获**：能批量导入大数据集，能区分整体失败和单条失败，能配置 429 退避重试。

## 阶段五：Query DSL（05_query_dsl/）

**学什么**：bool 复合查询的四个子句，全文检索的 match 家族和相关性评分。

**为什么在这里**：这是 Elasticsearch 的核心能力。query/filter 上下文的区别直接决定性能和评分行为。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 9 | `01_bool_query.py` | `bool`(must/filter/should/must_not)、`minimum_should_match` | filter 不算分，must_not 排除，should 影响排序 |
| 10 | `02_full_text.py` | `match`(operator/fuzziness)、`match_phrase`、`multi_match` | OR/AND 区别，短语相邻要求，跨字段加权评分 |

**关键收获**：能组合复杂查询条件，能区分精确过滤和全文匹配，能用加权和容错优化召回。

## 阶段六：聚合（06_aggregations/）

**学什么**：桶聚合、指标聚合、嵌套子聚合、时间序列和管道聚合。

**为什么在这里**：Elasticsearch 不只是搜索引擎，也是强大的实时分析引擎。聚合是日志分析和数据看板的基础。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 11 | `01_metrics_and_buckets.py` | `terms`、`range`、`stats`、`avg`、`size=0` | 分桶 + 桶内指标，size=0 只要聚合不要命中 |
| 12 | `02_pipeline_and_date.py` | `date_histogram`、`cumulative_sum`、query+aggs | 聚合受 query 过滤，管道聚合基于已有桶二次计算 |

**关键收获**：能做分组统计和区间分布，能做时间序列分析和累计计算，理解聚合与查询的组合。

## 阶段七：分页（07_pagination/）

**学什么**：`from/size` 浅分页的代价和上限，`search_after` + PIT 的深度翻页。

**为什么在这里**：分页是每个列表接口都要面对的问题。深翻页用错方式会拖垮集群。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 13 | `01_from_size.py` | `from_`、`size`、`sort`、`max_result_window` | from=10000 触发上限错误 |
| 14 | `02_search_after_pit.py` | `open_point_in_time`、`search_after`、`close_point_in_time` | PIT 锁定快照，按 sort 值翻页无重无漏，用完必须 close |

**关键收获**：能为浅分页和深度遍历选对方案，理解 PIT 是有状态资源必须释放。

## 阶段八：错误与恢复（08_errors_recovery/）

**学什么**：客户端异常类型的区分处理，乐观并发控制处理写冲突。

**为什么在这里**：生产代码必须能区分 404/400/409/5xx 并做出正确反应，而不是统一 catch。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 15 | `01_exception_types.py` | `NotFoundError`、`BadRequestError`、`ignore_status` | 用 exists/ignore_status 处理可预期 404，区分 4xx/5xx |
| 16 | `02_optimistic_concurrency.py` | `if_seq_no`、`if_primary_term`、`ConflictError` | 过期版本写入触发 409，重读后重试成功 |

**关键收获**：能写出可区分处理的错误恢复代码，能用乐观锁安全处理并发更新。

## 阶段九：生产实践（09_production/）

**学什么**：alias + reindex 实现零停机 mapping 变更，异步客户端并发检索。

**为什么在这里**：mapping 不可变是硬约束，线上变更必须有零停机方案；高并发服务需要异步客户端。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 17 | `01_alias_reindex.py` | `update_aliases`、`reindex`、蓝绿切换 | 应用始终查 alias，底层 v1→v2 原子切换不中断 |
| 18 | `02_async_client.py` | `AsyncElasticsearch`、`async with`、`asyncio.gather`、`async_bulk` | 并发查询，async with 自动关闭连接 |

**关键收获**：能设计索引版本切换流程，能把同步代码迁移到异步服务而不泄漏连接。

## 阶段十：高级 DSL（10_dsl/）

**学什么**：用 `elasticsearch.dsl` 以面向对象方式建模文档和构建查询。

**为什么在这里**：复杂查询用 dict 写难以维护。DSL 提升可读性和复用性，但与底层 client 等价，放最后便于对照理解。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 19 | `01_document_orm.py` | `Document`、`Search`、`Q`、`to_dict` | 类声明 mapping，链式构建查询，`to_dict` 看等价底层 DSL |

**关键收获**：能看懂并使用 DSL 高级 API，能在 dict 和 DSL 之间互转排查问题。

## 阶段十一：高级检索（11_advanced_search/）

**学什么**：高亮、字段裁剪、折叠去重、向量 kNN 与混合召回、按条件批量改删。

**为什么在这里**：基础检索跑通后，真实检索产品还需要高亮命中、控制返回体积、按业务去重、语义召回和批量维护数据。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 20 | `01_highlight_source.py` | `highlight`、`pre_tags`、`_source` includes/excludes | 命中词被标签包裹，返回字段被裁剪 |
| 21 | `02_collapse_dedup.py` | `collapse`、`inner_hits` | 每个分组只返回代表文档，inner_hits 取组内更多 |
| 22 | `03_knn_vector.py` | `dense_vector`、`knn`、关键词+向量混合 | 向量相似度召回，混合检索合并两种得分 |
| 23 | `04_by_query_ops.py` | `update_by_query`、`delete_by_query`、`conflicts="proceed"` | 按条件批量改/删，打印受影响文档数 |

**关键收获**：能做出有高亮、去重、语义召回的检索体验，能用 by_query 做批量数据维护并处理并发冲突。

## 阶段十二：索引与性能（12_index_and_performance/）

**学什么**：分片/副本/刷新间隔等索引设置、批量导入调优、索引模板、慢查询剖析和请求合并。

**为什么在这里**：检索能力齐备后，要让它在真实数据量下跑得快、可运维。这是从“能用”到“好用”的关键一跳。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 24 | `01_index_settings.py` | `number_of_shards/replicas`、`refresh_interval`、`forcemerge` | 导入前关 refresh、导入后恢复并 force merge 的调优套路 |
| 25 | `02_index_template.py` | `put_index_template`、`index_patterns`、`priority` | 匹配命名的新索引自动套用 mapping/settings |
| 26 | `03_profile_msearch.py` | `profile=True`、`msearch` | 查询耗时分解定位慢点，一次请求取回多组结果 |

**关键收获**：能为写入和查询做基本调优，能用模板统一时序索引族，能用 profile/msearch 排查和减少往返。

## 学完示例后

阅读 `templates/`：

1. `settings.py`：统一连接配置和索引命名。
2. `client_factory.py`：同步/异步客户端工厂，注入超时和重试。
3. `sync_repository.py`：同步脚本/离线任务的仓储骨架。
4. `async_repository.py`：异步服务/worker 的仓储骨架。
