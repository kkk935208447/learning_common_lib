# 常见陷阱

本文按学习阶段整理“现象、根因、修复方式”和对应示例。建议和 [best_practices.md](best_practices.md) 对照阅读：最佳实践讲应该做什么，本文讲踩坑后怎么定位。

主题导航：

- 数据协议与写入：1、2、3、4、9。
- 查询、分页与一致性：5、6、10、11、12、13、14。
- 异步与资源管理：7、8、19。
- 发布、分区与混合检索：15、16、17、18。

## 1. 维度和 embedding 模型不一致

**现象**：写入或搜索时报维度错误，或者召回结果完全不相关。

**根因**：collection 的 `FLOAT_VECTOR dim` 与实际 embedding 维度不同；或者索引使用旧模型维度，查询使用新模型维度。

**修复方式**：

- 把维度定义集中在配置中。
- 写入前调用 `ensure_vector(vector, dimension=...)`。
- 更换 embedding 模型时创建新 collection 或新索引版本，不要混写。

对应示例：`examples/01_basics/02_dimension_validation.py`

## 2. 没有稳定主键导致重复数据

**现象**：导入任务失败重跑后，搜索结果出现大量重复 chunk。

**根因**：使用自增 ID 或随机 ID，重跑无法覆盖旧记录。

**修复方式**：

- 用 `document_id + chunk_no + version` 生成稳定主键。
- 批量导入优先使用 `upsert`。
- 写入完成后用 `query` 验证同一 source 或 document 的数量。

对应示例：`examples/04_errors_and_recovery/02_idempotent_upsert.py`

## 3. filter 拼接用户输入

**现象**：查询语法错误、越权访问、过滤条件被绕过。

**根因**：把用户输入直接拼进 `filter` 字符串。

**修复方式**：

- filter 字段采用白名单。
- 字符串值必须转义或由封装函数生成。
- 权限过滤应在服务层统一注入，不交给前端传完整表达式。

对应示例：`examples/03_filter_and_crud/02_scalar_filter_query_delete.py`

## 4. 把 `query` 当成向量检索

**现象**：只返回标量字段匹配结果，没有相似度排序。

**根因**：`query` 是标量查询，`search` 才是向量 ANN 检索。

**修复方式**：

- 需要语义相似度时使用 `search(data=[query_vector], ...)`。
- 只按 ID、source、tenant 查询元数据时使用 `query`。
- RAG 中常用 `search + filter`，而不是先 `query` 再手动排序。

## 5. collection 加载和索引顺序错误

**现象**：collection 创建后无法搜索，或 load 时报缺少向量索引。

**根因**：没有在加载前创建向量索引。

**修复方式**：

- 创建 collection 时同时传入 `schema` 和 `index_params`。
- 如果先创建 collection，再补索引，要按“插入 → create_index → load_collection → search”的顺序。
- 教程默认使用 `AUTOINDEX` 降低初学阶段的索引配置负担。

## 6. Milvus Lite 被代理变量影响

**现象**：`milvus_lite` 已安装，`MilvusClient(".milvus_tutorial/demo.db")` 仍然报 `Fail connecting to server on 127.0.0.1:<port>`。

**根因**：Milvus Lite 会在本机随机端口启动 gRPC 服务。如果环境里设置了 `HTTP_PROXY`、`HTTPS_PROXY` 或同名小写变量，但 `NO_PROXY/no_proxy` 没有正确包含 `127.0.0.1,localhost`，gRPC 连接可能被代理接管并超时。

**修复方式**：

- 示例脚本顶部调用 `ensure_local_no_proxy()`，自动补齐 `NO_PROXY/no_proxy`。
- 手动运行时也可以显式设置：`NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost`。
- 只有在本机端口确实不可监听时，才改用 Docker Standalone 并设置 `MILVUS_URI=http://localhost:19530`。

对应示例：`examples/03_filter_and_crud/01_lite_insert_search.py`

## 7. 在异步服务里每个请求创建客户端

**现象**：并发升高后连接数飙升、延迟抖动、关闭时资源泄漏。

**根因**：把 `AsyncMilvusClient()` 放在请求函数内部，每次请求都新建连接。

**修复方式**：

- 在 FastAPI lifespan 或 worker 启动阶段创建客户端。
- 请求处理只复用已创建的 repository。
- 服务关闭时 `await client.close()` 或退出 `async with`。

对应示例：`examples/05_async_client/02_async_lifecycle_policy.py`

## 8. 异步并发没有上限

**现象**：`asyncio.gather` 一次发出大量检索请求，Milvus 或网络被压垮。

**根因**：误以为 async 等于无限并发。

**修复方式**：

- 用 `asyncio.Semaphore` 限制并发。
- 对批量查询拆批。
- 记录耗时、错误率和队列长度。

对应模板：`templates/async_repository.py`

## 9. 误删生产集合

**现象**：调试脚本执行后真实 collection 消失。

**根因**：清理脚本没有集合名前缀限制，或者默认调用 `drop_collection`。

**修复方式**：

- 集合名强制加业务前缀或教程前缀。
- 示例只删除自己创建的集合。
- 生产清理脚本必须显示待删除列表并要求确认。

对应示例：`examples/02_schema_index/02_collection_name_policy.py`

## 10. 盲目复制索引参数

**现象**：索引能创建，但召回变差、延迟升高或内存暴涨。

**根因**：把示例里的 `nlist`、`nprobe`、`M`、`efConstruction`、`ef` 当成固定答案，没有结合数据量、向量分布和延迟目标压测。

**修复方式**：

- 先用 `AUTOINDEX` 或 `FLAT` 建基线。
- 用业务评测集比较召回、延迟、内存和构建时间。
- 把索引参数纳入配置和发布记录。

对应示例：`examples/06_index_and_search_params/01_index_catalog.py`

## 11. 混淆构建参数和搜索参数

**现象**：把 `nprobe` 写进 `add_index(params=...)`，或把 `nlist` 写进 `search_params`，参数不生效或报错。

**根因**：没有区分“建索引时确定的数据结构”和“查询时控制召回范围”的参数。

**修复方式**：

- `nlist`、`M`、`efConstruction`、`m`、`nbits` 属于构建参数。
- `nprobe`、`ef`、`radius`、`range_filter` 属于搜索参数。
- 参数写入位置参考 `02_build_multiple_index_params.py` 和 `03_range_search_params.py`。

## 12. 大结果集一次性查询

**现象**：后台导出、巡检或长列表查询时内存升高，接口等待时间过长。

**根因**：把 `query(limit=...)` 或大 topK `search` 当成分页接口，一次性拉取大量结果。

**修复方式**：

- 标量导出使用 `query_iterator(batch_size=...)`。
- 大 topK 向量检索使用 `search_iterator(batch_size=...)`。
- iterator 必须在 `finally` 中 `close()`。

对应示例：`examples/06_index_and_search_params/04_iterators_large_results.py`

## 13. RAG 检索没有按文档去重

**现象**：topK 里同一篇文档的相邻 chunk 占了多个位置，最终 prompt 上下文缺少多样性。

**根因**：只按 chunk 相似度排序，没有使用 `document_id` 做 grouping search。

**修复方式**：

- schema 中保留稳定的 `document_id` 字段。
- 检索时用 `group_by_field="document_id"`。
- 用 `group_size` 控制每篇文档最多返回几个代表 chunk。

对应示例：`examples/06_index_and_search_params/05_grouping_search.py`

## 14. 不理解一致性级别就复制 `Strong`

**现象**：所有 collection 都设置 `consistency_level="Strong"`，但没人知道为什么；或写完后偶发读不到数据时只怀疑 SDK。

**根因**：没有区分 collection 默认一致性和单次 query/search 的一致性覆盖，也没有理解 `Strong`、`Bounded`、`Eventually`、`Session` 的取舍。

**修复方式**：

- 本地 smoke 和写后立即验证可以用 `Strong`。
- 在线读路径通常从默认 `Bounded` 开始评估。
- 能接受短暂旧数据的场景才考虑 `Eventually`。

对应示例：`examples/04_errors_and_recovery/03_consistency_levels.py`

## 15. partition 被当成权限系统

**现象**：系统给每个用户或每份文档创建 partition，collection 元数据管理变复杂，检索维护成本升高。

**根因**：把 partition 当成万能隔离手段，而不是粗粒度物理分区。

**修复方式**：

- 少量租户、大类目、冷热数据可以考虑 partition。
- 高频权限、来源、文档级过滤优先用 scalar filter。
- 设计 partition 前先估算数量上限、生命周期和清理策略。

对应示例：`examples/07_partitions_aliases/01_partition_lifecycle.py`

## 16. partition key 和手动 partition 混用无边界

**现象**：同一个系统既给每个租户创建手动 partition，又在 schema 上设置 partition key，排查数据路由时很难判断走了哪条路径。

**根因**：没有区分“少量粗粒度手动分区”和“高基数字段自动路由”。

**修复方式**：

- 少量版本、冷热、大类目使用手动 partition。
- 多租户、namespace 这类高基数字段优先评估 partition key。
- 权限过滤仍然保留 scalar filter，不把 partition key 当权限系统。

对应示例：`examples/07_partitions_aliases/03_partition_key.py`

## 17. 在线服务直接绑定物理 collection

**现象**：新索引上线需要改配置或重启服务，回滚困难。

**根因**：服务查询固定 collection 名，例如 `kb_docs_v1`，没有通过 alias 解耦。

**修复方式**：

- 服务固定查询 alias，例如 `kb_current`。
- 新版本写入 `kb_docs_v2`。
- 验证通过后使用 `alter_alias` 切换。
- 出问题时把 alias 指回旧 collection。

对应示例：`examples/07_partitions_aliases/02_alias_switching.py`

## 18. BM25 字段创建太晚

**现象**：已经上线 dense collection 后，想直接在查询时加 BM25 hybrid search，但缺少 sparse 字段和 BM25 function。

**根因**：BM25 不是简单查询参数，需要 schema 中提前声明 analyzer、稀疏向量字段和 `FunctionType.BM25`。

**修复方式**：

- 在 collection 创建期设计 `text`、`sparse_vector`、BM25 function 和 sparse index。
- 已上线 collection 需要新增 BM25 时，创建新 collection 并用 alias 切换。

对应示例：`examples/08_hybrid_search/02_bm25_schema.py`

## 19. 示例导入写成隐式路径依赖

**现象**：从教程目录能运行，从仓库根目录、IDE 或 smoke 中运行就找不到模块。

**根因**：示例依赖当前工作目录导入，或模板只支持相对导入但又被直接当作脚本运行。

**修复方式**：

- `examples/` 尽量自包含，不依赖模板模块。
- `templates/` 优先使用包内相对导入，直接运行文件时再回退到 `templates.*` 绝对导入。
- smoke 同时覆盖模板的 `python -m` 模块运行和直接文件运行。
