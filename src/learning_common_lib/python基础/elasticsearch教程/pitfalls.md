# 常见坑与排查（pitfalls）

本文记录使用 Elasticsearch + Python 客户端时的高频错误，给出现象、根因、修复方式和对应示例。其中多数坑在本教程开发过程中真实遇到过。

## 1. 客户端与服务端版本不匹配

**现象**：
```
BadRequestError(400, 'media_type_header_exception',
'Invalid media-type value on headers [Accept, Content-Type]',
Accept version must be either version 8 or 7, but found 9.')
```

**根因**：Elasticsearch 客户端会在请求头声明 `compatible-with=<客户端大版本>`，服务端只接受同大版本。9.x 客户端连 8.x 服务端必然失败。

**修复**：把客户端固定到与服务端相同的大版本。本教程服务端是 8.19.x，所以依赖写为：
```toml
"elasticsearch[async]>=8.19,<9"
```
改完执行 `uv sync`，确认 `elasticsearch.__version__` 的首位与服务端一致。

**对应示例**：`01_basics/01_connect_and_info.py` 会打印 `client_major` 和 `server_version` 供核对。

## 2. 单节点 ES 被密集请求 OOM

**现象**：连续运行多个示例后突然大面积报 `ConnectionTimeout` / `Connection reset by peer` / `ServerDisconnected`，`docker ps` 显示容器刚重启（`Up X seconds`）。

**根因**：单节点 ES 默认堆内存有限，短时间内大量建索引 + reindex + 聚合会触发 OOM，容器被杀后自动重启，期间所有连接失败。

**修复**：
- 给容器配足够堆内存：`-e "ES_JAVA_OPTS=-Xms1g -Xmx1g"`。
- 串行运行示例时在用例之间留间隔（smoke 脚本已内置 `ES_SMOKE_GAP`，默认 1 秒）。
- 示例运行完及时 `drop` 教学索引，减少常驻分片数。

**对应**：`smoke/run_all_examples.py` 先探测连通性，再逐个运行并留间隔。

## 3. text 字段 term 查不到 / keyword 字段 match 行为怪异

**现象**：`term` 查 `text` 字段查不到精确值；或对 `text` 字段做 `terms` 聚合报错。

**根因**：`text` 字段被分词存储（如 `"Search Engine"` → `["search","engine"]`），`term` 要求整体精确匹配，自然命中不了；聚合默认需要 `keyword` 这类 doc_values 字段。

**修复**：
- 精确匹配、过滤、聚合、排序用 `keyword`。
- 全文检索用 `text`。
- 两者都要时用 multi-field：`{"type":"text","fields":{"raw":{"type":"keyword"}}}`，检索用 `title`，聚合用 `title.raw`。

**对应示例**：`02_mapping_analysis/01_field_types.py`、`02_custom_analyzer.py`。

## 4. 刚写入立刻搜不到

**现象**：`index` 成功后立刻 `search`，命中数为 0。

**根因**：ES 近实时（NRT）。文档写入后要经过 refresh（默认 1 秒）生成新 segment 才可搜。

**修复**：
- 测试/教学场景用 `refresh="wait_for"` 或写完调 `indices.refresh`。
- 生产**不要**每次写都 `refresh="wait_for"`，会严重拖慢吞吐；接受默认 1 秒延迟或按需调 `refresh_interval`。

**对应示例**：所有写入示例都显式 refresh 以保证可观察。

## 5. mapping 创建后改不动

**现象**：想把字段类型从 `text` 改成 `keyword`，或新增子字段，`put_mapping` 报错或不生效。

**根因**：已存在字段的类型不可变。

**修复**：走零停机迁移——新建带正确 mapping 的索引，`reindex` 数据过去，再用 `update_aliases` 原子切换 alias。

**对应示例**：`09_production/01_alias_reindex.py`。

## 6. 深度分页报错或很慢

**现象**：
```
search_phase_execution_exception ... Result window is too large,
from + size must be less than or equal to: [10000]
```
或翻到很后面响应越来越慢。

**根因**：`from/size` 模式下每个 shard 都要取 `from+size` 条再归并，代价随 `from` 线性增长；且默认 `max_result_window=10000`。

**修复**：深翻页和全量遍历改用 `search_after` + Point In Time；离线遍历用 `helpers.scan`。

**对应示例**：`07_pagination/01_from_size.py`（复现上限错误）、`02_search_after_pit.py`（正确方案）。

## 7. search_after 漏数据或重复

**现象**：用 `search_after` 翻页，结果有遗漏或重复。

**根因**：sort 字段不唯一时，值相同的文档边界不确定，会漏或重；或者翻页期间 segment 合并导致顺序漂移。

**修复**：
- sort 加一个唯一字段兜底，配合 PIT 用 `_shard_doc`。
- 全程在同一个 PIT 快照内翻页，避免数据漂移。

**对应示例**：`07_pagination/02_search_after_pit.py` 用 `[{"seq":"asc"},{"_shard_doc":"asc"}]`。

## 8. PIT 资源泄漏

**现象**：大量 PIT 累积，集群打开的 search context 持续增长。

**根因**：`open_point_in_time` 后没有 `close_point_in_time`，PIT 在 `keep_alive` 到期前一直占资源。

**修复**：用 `try/finally` 保证关闭，`keep_alive` 设成够用的最小值。

**对应示例**：`07_pagination/02_search_after_pit.py` 在 `finally` 里 close。

## 9. 并发更新互相覆盖

**现象**：两个进程同时更新同一文档，后写的覆盖先写的，丢失更新。

**根因**：`update`/`index` 默认是“最后写入获胜”，没有版本检查。

**修复**：读时记录 `_seq_no` 和 `_primary_term`，写时带 `if_seq_no`/`if_primary_term`，冲突抛 `ConflictError` 后重读重试。

**对应示例**：`08_errors_recovery/02_optimistic_concurrency.py`。

## 10. bulk 部分失败被忽略

**现象**：`helpers.bulk` 返回成功，但实际有文档没写进去。

**根因**：`bulk` 默认 `raise_on_error=True`，遇错抛异常；若用了 `raise_on_error=False` 又不检查返回的 errors 列表，失败就被静默吞掉。

**修复**：检查 `helpers.bulk` 返回的 `(success_count, errors)`，对 errors 做日志或重试；`streaming_bulk` 逐条检查 `ok` 标志。

**对应示例**：`04_bulk/01_bulk_helpers.py`。

## 11. 本机连接被代理拦截

**现象**：明明 `curl localhost:9200` 正常，Python 客户端却连不上或超时。

**根因**：环境设了 `HTTP_PROXY`/`HTTPS_PROXY`，客户端请求被代理拦截。

**修复**：把 `127.0.0.1,localhost` 加进 `NO_PROXY` 和 `no_proxy`。

**对应**：所有示例的 `ensure_local_no_proxy()`。

## 12. 异步客户端连接泄漏

**现象**：`AsyncElasticsearch` 用完不关，进程退出报 unclosed connector 警告，或连接数耗尽。

**根因**：异步客户端持有 aiohttp 连接池，必须显式关闭。

**修复**：用 `async with AsyncElasticsearch(...) as client:`，或在 `finally` 里 `await client.close()`。

**对应示例**：`09_production/02_async_client.py`。

## 13. kNN 向量维度或相似度不匹配

**现象**：写入向量报 `dimensions does not match`，或 kNN 检索结果明显不对、得分异常。

**根因**：`dense_vector` 的 `dims` 必须和 embedding 模型输出维度严格一致；`similarity`（cosine/dot_product/l2_norm）要和向量是否归一化匹配。`dot_product` 要求向量已归一化，否则结果错乱。

**修复**：
- `dims` 写成模型实际维度（如 384/768/1536），不要写错。
- 用 `cosine` 最稳妥；若用 `dot_product` 必须先 L2 归一化向量。
- kNN 召回不全时调大 `num_candidates`。

**对应示例**：`11_advanced_search/03_knn_vector.py`。

## 14. update_by_query / delete_by_query 中途版本冲突

**现象**：`update_by_query` 或 `delete_by_query` 返回里 `version_conflicts > 0`，部分文档没改到。

**根因**：by_query 基于快照执行，期间若有其他写入改了文档版本，默认会冲突中止。

**修复**：
- 加 `conflicts="proceed"` 跳过冲突文档继续处理，事后看 `version_conflicts` 决定是否重跑。
- 对一致性要求高的场景，先停写或在低峰执行。
- 注意 by_query 是重操作，大范围更新考虑分批 + `slices`。

**对应示例**：`11_advanced_search/04_by_query_ops.py`。

## 15. 对写入中的索引做 force merge

**现象**：`forcemerge(max_num_segments=1)` 后写入变慢，或 merge 长时间不结束、占用大量 IO。

**根因**：force merge 是为只读/冷索引设计的。对持续写入的索引强制合并到 1 个 segment，会和正常的 segment 生成相互拖累。

**修复**：只对不再写入的索引（如已滚动的历史索引）做 force merge；活跃索引交给 ES 自动的后台 merge。

**对应示例**：`12_index_and_performance/01_index_settings.py`（演示在导入完成后才 merge）。
