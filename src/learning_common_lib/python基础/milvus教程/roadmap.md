# Milvus API 全景与学习路线

本文回答“应该按什么顺序学 Milvus 教程，以及每个示例为什么放在这个位置”。先用 [README.md](README.md) 完成环境准备和快速开始，再按本文逐个运行示例；需要工程分层时看 [architecture_map.md](architecture_map.md)，需要结论性取舍时看 [best_practices.md](best_practices.md)。

## 阅读方式与版本要求

- Python `>=3.11,<3.12`
- `pymilvus[milvus-lite]>=3.0.0`
- 第一、二阶段包含部分纯 Python 协议和 schema 构造示例，用于先理解数据边界。
- 第三到第八阶段默认使用 Milvus Lite DB 真实执行 API；也可通过 `MILVUS_URI=http://localhost:19530` 连接 Standalone。
- 若本机配置了 HTTP/HTTPS 代理，示例会自动把 `127.0.0.1,localhost` 加入 `NO_PROXY/no_proxy`，避免 Milvus Lite 本机 gRPC 连接走代理。
- `examples/` 示例优先自包含，允许重复少量 helper，以保证打开单个文件就能理解。

## API 全景

本文不把重点放在 RAG 流程本身，而是按 Milvus Python SDK 的对象、方法和参数建立学习地图。你可以先看下面的全景表，知道每个 API 解决什么问题，再进入对应阶段运行示例。

### Milvus 工程使用流程

先看工程链路，再看后面的 API 表。大多数 Milvus 项目都可以拆成建模、导入、检索、发布和运维几条线：

```text
连接自检：
MilvusClient(uri, token, timeout)
  -> get_server_version() / list_collections()
  -> has_collection() / describe_collection()

索引创建：
确定主键和字段协议
  -> create_schema(auto_id, enable_dynamic_field)
  -> schema.add_field(...)
  -> prepare_index_params()
  -> add_index(field_name, index_type, metric_type, params)
  -> create_collection(schema, index_params, consistency_level) # 传入 schema + index_params 创建时通常会自动建索引并 load
  -> describe_collection() / list_indexes() / describe_index()

数据导入：
Document / 原始数据
  -> 清洗文本、生成 embedding、校验维度
  -> 转成 Milvus row dict
  -> insert(data) 或 upsert(data)
  -> query(filter) / get(ids) / get_collection_stats() 验证写入结果

检索时：
构造 query embedding
  -> 确认 collection 已加载：自动 load 或显式 load_collection() + get_load_state()，因为有时候可能释放过collection 【release_collection()】 会释放索引，导致检索失败
  -> search(data, anns_field, search_params, filter, limit, output_fields)
  -> 按需加 partition_names / consistency_level
  -> 可选 group_by_field 做文档级去重
  -> 返回 hit.id / hit.distance / hit.entity

大结果集：
标量导出 -> query_iterator(batch_size, limit, filter, output_fields) -> close()
向量批量消费 -> search_iterator(data, batch_size, limit, search_params) -> close()

混合检索：
dense 字段 + sparse/BM25 字段
  -> 每路构造 AnnSearchRequest(data, anns_field, param, limit, filter)
  -> hybrid_search(reqs, ranker, limit, output_fields)
  -> RRFRanker 建基线，WeightedRanker 做评估后的加权融合

发布与回滚：
新 collection 建模和导入
  -> 验证 search/query/stats
  -> create_alias() 或 alter_alias() 切换稳定入口
  -> describe_alias() 确认指向
  -> 异常时 alter_alias() 回旧 collection

Standalone 运维：
create_collection / create_index
  -> flush()
  -> load_collection()
  -> get_load_state()
  -> search/query
  -> release_collection() / compact() / get_collection_stats()
```

### API 参数速查概览

这张表只做概览，详细取舍仍看每个示例顶部 docstring、后续 API 分节和官方文档。

| API/对象 | 常见参数 | 参数说明 | 主要示例 |
|----------|----------|----------|----------|
| `MilvusClient(...)` / `AsyncMilvusClient(...)` | `uri`、`token`、`user`、`password`、`db_name`、`timeout` | `uri` 可以是 Lite DB 文件或服务端地址；`token` 常用于云服务或开启认证的服务端；`user/password` 是 PyMilvus 支持的另一种认证写法；`db_name` 指定 database；`timeout` 限制单次调用等待时间 | `03_filter_and_crud/01_lite_insert_search.py`、`05_async_client/` |
| `create_schema(...)` | `auto_id`、`enable_dynamic_field` | `auto_id=True` 由 Milvus 生成主键，适合不关心外部幂等 ID 的写入；教程多数使用稳定主键和 `auto_id=False`；`enable_dynamic_field=True` 允许未声明字段进入动态 metadata，但稳定过滤字段更推荐显式建模 | `02_schema_index/01_build_schema_and_index.py` |
| `schema.add_field(...)` | `field_name`、`datatype`、`is_primary`、`auto_id`、`max_length`、`dim`、`nullable`、`default_value`、`element_type`、`max_capacity`、`is_partition_key`、`is_clustering_key`、`enable_analyzer`、`analyzer_params` | `field_name` 是字段名；`datatype` 用 `DataType` 指定字段类型；`is_primary/auto_id` 决定主键策略；`max_length` 用于 `VARCHAR`；`dim` 用于 `FLOAT_VECTOR`；`nullable/default_value` 控制空值和默认值；`element_type/max_capacity` 用于 `ARRAY`；`is_partition_key` 声明自动分区路由字段；`is_clustering_key` 属于服务端数据布局优化参数；`enable_analyzer/analyzer_params` 让文本字段可用于 BM25 等全文检索 | `02_schema_index/01_build_schema_and_index.py`、`07_partitions_aliases/03_partition_key.py`、`08_hybrid_search/02_bm25_schema.py` |
| `prepare_index_params()` / `add_index(...)` | `field_name`、`index_name`、`index_type`、`metric_type`、`params` | `field_name` 指要建索引的向量字段；`index_name` 是索引名；`index_type` 选择 `AUTOINDEX`、`IVF_FLAT`、`HNSW`、`SPARSE_INVERTED_INDEX` 等；`metric_type` 要和搜索时一致；`params` 放 `nlist`、`M`、`efConstruction`、`inverted_index_algo` 等构建参数 | `06_index_and_search_params/01_index_catalog.py`、`02_build_multiple_index_params.py` |
| `create_collection(...)` | `collection_name`、`dimension`、`primary_field_name`、`id_type`、`vector_field_name`、`metric_type`、`auto_id`、`schema`、`index_params`、`consistency_level`、`properties`、`timeout` | 简单模式可直接传 `dimension` 等参数；生产更推荐显式传 `schema/index_params`；`consistency_level` 决定默认读一致性；`properties` 用于 collection 级配置；`timeout` 避免 DDL 无限等待 | `03_filter_and_crud/01_lite_insert_search.py` |
| `insert(...)` / `upsert(...)` | `collection_name`、`data`、`partition_name`、`timeout` | `data` 是 dict 或 dict 列表，字段必须和 schema 对齐；`insert` 偏新增；`upsert` 按主键插入或覆盖，适合可重跑导入；`partition_name` 指定写入的手动分区 | `03_filter_and_crud/01_lite_insert_search.py`、`04_errors_and_recovery/02_idempotent_upsert.py` |
| `get(...)` / `query(...)` / `delete(...)` | `ids`、`filter`、`filter_params`、`output_fields`、`partition_names`、`partition_name`、`limit`、`offset`、`timeout` | `get` 按主键取实体；`query` 按 scalar filter 查实体，不计算向量相似度；`delete` 可按主键或 filter 删除；`filter_params` 适合表达式参数绑定；`output_fields` 控制返回字段；`partition_names` 限制读取分区；`limit/offset` 只适合有限结果，不替代 iterator | `03_filter_and_crud/02_scalar_filter_query_delete.py` |
| `search(...)` | `data`、`anns_field`、`filter`、`filter_params`、`limit`、`offset`、`output_fields`、`search_params`、`partition_names`、`consistency_level`、`round_decimal`、`timeout` | `data` 是查询向量列表；`anns_field` 指向量字段；`filter` 做 scalar 过滤；`filter_params` 避免手写拼接表达式参数；`limit` 是 TopK 或分组数；`offset` 只适合浅分页；`output_fields` 控制实体字段；`search_params` 放度量和索引搜索参数；`partition_names` 限定扫描分区 | `03_filter_and_crud/01_lite_insert_search.py`、`06_index_and_search_params/03_range_search_params.py` |
| `search_params` | `metric_type`、`params.nprobe`、`params.ef`、`params.radius`、`params.range_filter`、`params.search_list`、`params.reorder_k`、`params.drop_ratio_search` | `metric_type` 要和索引一致；`nprobe/ef/search_list/reorder_k` 通常越大召回越高、延迟越高；`radius/range_filter` 用于范围检索，方向受 `COSINE/IP/L2` 影响；`drop_ratio_search` 常见于稀疏检索裁剪，必须用业务样本校准 | `06_index_and_search_params/03_range_search_params.py` |
| `query_iterator(...)` / `search_iterator(...)` | `batch_size`、`limit`、`filter`、`output_fields`、`search_params`、`partition_names`、`round_decimal`、`close()` | iterator 用于分批读取，避免一次性拉取大结果；`batch_size` 控制单批大小；`limit=-1` 表示尽量遍历；用完必须 `close()` | `06_index_and_search_params/04_iterators_large_results.py`、`09_standalone_ops/04_search_iterator_v2.py` |
| `search(group_by_field=...)` | `group_by_field`、`group_size`、`strict_group_size` | `group_by_field` 指分组字段；`group_size` 控制每组实体数；`strict_group_size=True` 要求每组尽量返回足量实体；`limit` 表示返回多少个组 | `06_index_and_search_params/05_grouping_search.py` |
| `AnnSearchRequest(...)` / `hybrid_search(...)` | `data`、`anns_field`、`param`、`limit`、`filter`、`expr_params`、`reqs`、`ranker`、`output_fields` | 每个向量字段一个 `AnnSearchRequest`；请求级 `limit` 是单路召回数；`hybrid_search.limit` 是融合后最终数量；`RRFRanker` 建基线，`WeightedRanker` 用评测后的权重融合 | `08_hybrid_search/01_hybrid_request.py` |
| `Function(..., FunctionType.BM25)` | `name`、`input_field_names`、`output_field_names`、`function_type`、`params` | BM25 需要在 schema 创建期声明：文本字段启用 analyzer，Function 把文本字段写入稀疏向量输出字段，再给稀疏字段建索引；`params` 用于函数级可选配置 | `08_hybrid_search/02_bm25_schema.py` |
| partition / alias API | `collection_name`、`partition_name`、`partition_names`、`alias`、`timeout` | 手动 partition 适合少量粗粒度物理隔离；`partition_names` 限制检索范围；alias 用稳定逻辑名指向物理 collection，支持蓝绿切换和回滚 | `07_partitions_aliases/` |
| Standalone 运维 API | `load_collection`、`release_collection`、`get_load_state`、`flush`、`compact`、`get_collection_stats` | Standalone 需要显式 load 才能稳定检索；`flush` 封口 growing segment；`compact` 合并回收删除空间；这些在 Lite 中会被隐藏或简化 | `09_standalone_ops/` |

### 客户端与连接

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `MilvusClient(...)` | `uri`、`token`、`user`、`password`、`db_name`、`timeout` | 同步客户端；同一套代码可连接 Lite DB 文件、Standalone 或云服务 | 阶段三 |
| `AsyncMilvusClient(...)` | `uri`、`token`、`user`、`password`、`db_name`、`timeout` | 异步客户端；适合 FastAPI、异步 worker、批量并发查询 | 阶段五 |
| `close()` | 无 | 关闭客户端连接；异步服务退出时必须清理 | 阶段五 |

参数要点：

- `uri=".milvus_tutorial/xxx.db"` 是 Milvus Lite DB 文件，不需要部署 Milvus。
- `uri="http://localhost:19530"` 是 Standalone 或 Distributed 服务端地址。
- `token` 用于云服务或开启认证的服务端；本地 Standalone 默认可留空。
- PyMilvus 也支持 `user/password` 分开传入；本教程模板只保留 `MILVUS_TOKEN` 配置入口。
- `timeout` 建议在生产调用上显式传入，避免请求无限等待。
- 没有必要单独封装“ping”：脚本启动时可用 `get_server_version(timeout=...)` 或 `list_collections()` 做轻量连通性检查。

### Collection、schema 与字段

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `create_schema(...)` | `auto_id`、`enable_dynamic_field` | 创建 collection schema；决定主键是否自增、是否允许动态字段 | 阶段二 |
| `schema.add_field(...)` | `field_name`、`datatype`、`is_primary`、`auto_id`、`max_length`、`dim`、`nullable`、`default_value`、`element_type`、`max_capacity`、`is_partition_key`、`is_clustering_key`、`enable_analyzer`、`analyzer_params` | 定义主键、向量、文本、JSON/ARRAY/标量过滤字段、partition key、clustering key 和 BM25 analyzer | 阶段二、七、八 |
| `schema.add_function(...)` | `Function(name,input_field_names,output_field_names,function_type,params)` | 声明服务端派生字段，例如 BM25 从文本字段生成稀疏向量 | 阶段八 |
| `create_collection(...)` | `collection_name`、`dimension`、`primary_field_name`、`id_type`、`vector_field_name`、`metric_type`、`auto_id`、`schema`、`index_params`、`consistency_level`、`properties` | 创建 collection；简单模式可只传维度，生产更推荐传 schema 和 index_params | 阶段二、三 |
| `has_collection(...)` | `collection_name` | 判断 collection 是否存在，避免重复创建或误删 | 阶段三 |
| `drop_collection(...)` | `collection_name` | 删除 collection；教程只删除自己创建的 `learning_milvus_` 前缀集合 | 阶段三 |

常见字段类型：

| 类型 | 必填参数 | 常见用途 | 注意点 |
|------|----------|----------|--------|
| `INT64` / `VARCHAR` | 主键用 `is_primary=True`，`VARCHAR` 需要 `max_length` | 主键、来源、租户、文档 ID、类别 | 主键是否 `auto_id` 会影响导入任务能否幂等重跑 |
| `FLOAT_VECTOR` | `dim` | dense embedding 检索 | 写入向量和查询向量维度必须完全一致 |
| `SPARSE_FLOAT_VECTOR` | 通常配稀疏索引 | sparse embedding、BM25 输出字段 | sparse/BM25 常用 `IP` 或 `BM25` 度量，别和 dense 分数混着解释 |
| `JSON` | 无 | 不固定 metadata | 方便但边界松，稳定过滤字段优先建成独立 scalar 字段 |
| `ARRAY` | `element_type`、`max_capacity`，字符串元素还要 `max_length` | 标签、短列表属性 | 适合低复杂度数组条件，不要替代关系模型 |

参数要点：

- `FLOAT_VECTOR` 必须设置 `dim`，查询向量维度必须完全一致。
- 文本和主键字段通常需要 `max_length`，否则超长文本会在写入时失败。
- 全文检索字段可配 `enable_analyzer=True`，需要细调分词时再补 `analyzer_params` 或多 analyzer 配置。
- 需要过滤、排序或稳定排查的 metadata 优先做显式字段；`enable_dynamic_field=True` 更适合探索期。
- `enable_dynamic_field=False` 更适合教学和稳定工程边界；只有确实需要自由 metadata 时再打开。
- `is_partition_key=True` 是 schema 期设计，不能当成查询时临时参数。
- BM25 相关字段通常需要在 schema 创建期配置 analyzer、稀疏向量字段和 Function，漏掉后一般要新建 collection。

### 索引构建参数

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `prepare_index_params()` | 无 | 创建索引参数容器 | 阶段二、六 |
| `index_params.add_index(...)` | `field_name`、`index_type`、`metric_type`、`params` | 给向量字段配置索引类型、相似度度量和构建参数 | 阶段二、六 |
| `create_index(...)` | `collection_name`、`index_params`、`timeout` | 对已存在 collection 创建或补建索引 | 阶段九 |

常用索引与参数：

| 索引类型 | 构建参数 | 搜索参数 | 主要作用 |
|----------|----------|----------|----------|
| `AUTOINDEX` | 通常不传 `params` | 通常只传 `metric_type` | 默认基线；先跑通和小规模评估时优先使用 |
| `FLAT` | 无 | 无 | 暴力精确检索；适合小数据集或召回基线 |
| `IVF_FLAT` | `nlist` | `nprobe` | 聚类倒排；用 `nprobe` 在召回和延迟间取舍 |
| `IVF_SQ8` | `nlist` | `nprobe` | 量化压缩；降低内存但要验证召回损失 |
| `IVF_PQ` | `nlist`、`m`、`nbits` | `nprobe` | 更强压缩；`m` 需要和向量维度兼容 |
| `HNSW` | `M`、`efConstruction` | `ef` | 在线低延迟高召回常用；内存和构建成本更高 |
| `DISKANN` | 依部署能力而定 | `search_list` | 更偏大规模磁盘 ANN 场景 |
| `SCANN` | `nlist`、`with_raw_data` | `nprobe`、`reorder_k` | 候选召回后再重排 |
| `SPARSE_INVERTED_INDEX` | `inverted_index_algo` | `drop_ratio_search` 等 | 稀疏向量和混合检索 |

### 写入、读取与修改

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `insert(...)` | `collection_name`、`data`、`partition_name`、`timeout` | 插入新行；重复主键通常会失败或产生冲突 | 阶段三 |
| `upsert(...)` | `collection_name`、`data`、`partition_name`、`timeout` | 插入或覆盖；适合可重跑导入任务 | 阶段三、四 |
| `get(...)` | `collection_name`、`ids`、`output_fields`、`partition_names` | 按主键取回实体，不做向量相似度计算 | 阶段三 |
| `query(...)` | `collection_name`、`filter`、`filter_params`、`output_fields`、`ids`、`partition_names`、`limit`、`offset` | 按标量条件查询，不做向量相似度计算 | 阶段三、六 |
| `delete(...)` | `collection_name`、`ids`、`filter`、`partition_name` | 按主键或过滤条件删除实体 | 阶段三、四 |

参数要点：

- `data` 可以是一条 dict 或多条 dict；字段名必须和 schema 对齐。
- `partition_name` 是写入目标分区；`partition_names` 是读取或检索时限制扫描范围。
- `filter` 是 Milvus 表达式字符串，适合租户、来源、时间、文档 ID 等标量条件。
- `filter_params` 适合把外部参数绑定进表达式；当前 Lite 版本可能不完全支持模板表达式，上 Standalone 前要单独验证。
- `output_fields` 控制返回字段，避免把不需要的大文本或向量全部取回。
- `query` 不返回相似度；需要向量相似度时用 `search`。
- `insert/upsert/delete` 返回计数字段；`get/query` 返回实体 dict 列表；这些返回值要用于导入校验和删除确认。

### 向量检索、过滤与分页

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `search(...)` | `collection_name`、`data`、`anns_field`、`filter`、`filter_params`、`limit`、`offset`、`output_fields`、`search_params`、`partition_names`、`consistency_level`、`round_decimal`、`timeout` | 单字段向量检索，可叠加标量过滤、分区限制和搜索参数 | 阶段三、六 |
| `query_iterator(...)` | `batch_size`、`limit`、`filter`、`output_fields`、`partition_names`、`timeout` | 分批遍历标量查询结果，适合导出、巡检、后台任务 | 阶段六 |
| `search_iterator(...)` | `data`、`batch_size`、`limit`、`filter`、`output_fields`、`search_params`、`anns_field`、`round_decimal` | 分批消费较大的向量检索结果 | 阶段六、九 |

`search_params` 常见结构：

```python
search_params = {
    "metric_type": "COSINE",
    "params": {
        "nprobe": 16,
        "ef": 64,
        "radius": 0.8,
        "range_filter": 0.3,
    },
}
```

参数要点：

- `metric_type` 要和索引度量一致；常见值是 `COSINE`、`IP`、`L2`。
- `limit` 是 TopK 或分组数；`offset` 只适合浅分页，不要把它当成大结果集分页方案。
- `nprobe`、`ef`、`search_list`、`reorder_k` 等参数通常越大召回越高、延迟越高。
- `radius` 和 `range_filter` 是范围检索阈值，含义和大小方向受 metric type 影响，必须用业务样本校准。
- iterator 用完要 `close()`，推荐放在 `try/finally` 中。
- `search` 返回 `List[List[hit]]`，外层对应每个 query vector；单个 hit 里重点看 `id`、`distance` 和 `entity`。

### 高级检索组合

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `search(group_by_field=...)` | `group_by_field`、`group_size`、`strict_group_size` | 按字段分组返回结果，常用于同一文档多 chunk 去重 | 阶段六 |
| `AnnSearchRequest(...)` | `data`、`anns_field`、`param`、`limit`、`filter`、`expr_params` | hybrid search 中每个向量字段对应一个请求 | 阶段八 |
| `hybrid_search(...)` | `collection_name`、`reqs`、`ranker`、`limit`、`output_fields`、`partition_names`、`timeout` | 同时检索 dense/sparse/BM25 等多路结果并融合 | 阶段八 |
| `RRFRanker(...)` | `k` | Reciprocal Rank Fusion；不需要手动指定 dense/sparse 权重 | 阶段八 |
| `WeightedRanker(...)` | 权重参数、`norm_score` | 按权重融合多路检索结果 | 阶段八 |
| `FunctionType.BM25` | `input_field_names`、`output_field_names` | 在 schema 中声明服务端 BM25 稀疏向量生成逻辑 | 阶段八 |

参数要点：

- `hybrid_search` 的每一路向量字段都要单独构造 `AnnSearchRequest`。
- `AnnSearchRequest.limit` 是每一路召回数量，`hybrid_search.limit` 是融合后的最终返回数量。
- dense 通常用 `COSINE` 或 `IP`，sparse/BM25 通常用 `IP`，不要混淆分数含义。
- `RRFRanker` 适合先建立基线；`WeightedRanker` 适合已经有样本评估权重时使用。
- BM25 不是查询时临时打开的开关，而是 collection schema 的一部分。

### Partition、alias、一致性与运维

| API/对象 | 常用参数 | 作用 | 何时重点学习 |
|----------|----------|------|--------------|
| `create_partition(...)` / `drop_partition(...)` | `collection_name`、`partition_name` | 手动创建和删除粗粒度分区 | 阶段七 |
| `partition_names` | 读取或检索参数 | 查询时只扫描指定分区 | 阶段七 |
| `create_alias(...)` / `alter_alias(...)` / `drop_alias(...)` | `collection_name`、`alias` | 用稳定逻辑名指向物理 collection，支持蓝绿切换和回滚 | 阶段七 |
| `load_collection(...)` / `release_collection(...)` | `collection_name` | Standalone 上把 collection 加载到查询节点内存，或释放内存 | 阶段九 |
| `get_load_state(...)` | `collection_name` | 查看 collection 是否已加载 | 阶段九 |
| `flush(...)` | `collection_name` | Standalone 上把 growing segment 封口落盘 | 阶段九 |
| `compact(...)` | `collection_name`、`is_clustering`、`is_l0`、`target_size`、`target_size_unit` | 合并 segment、回收删除后的空间；属于重操作 | 阶段九 |
| `get_collection_stats(...)` | `collection_name` | 查看行数、segment 等统计信息 | 阶段九 |

参数要点：

- partition 适合少量粗粒度隔离；partition key 适合高基数字段自动路由；权限仍应靠业务鉴权和 scalar filter。
- alias 适合生产发布：新 collection 验证后 `alter_alias` 切换，异常时再切回旧 collection。
- Lite 会隐藏或简化 load/release、flush/compact、iterator V2 等服务端细节；上 Standalone 前必须单独验证。
- `consistency_level` 常见值为 `Strong`、`Bounded`、`Eventually`、`Session`；本地验证常用 `Strong`，在线默认可从 `Bounded` 评估。

### 管理类 API 了解项

下面这些也是常见 API，但不是本教程主线。你需要先知道它们存在，后续迁移到真实项目时再按需补充专项示例。

| API/对象 | 常用参数 | 作用 | 本教程处理方式 |
|----------|----------|------|----------------|
| `get_server_version(...)` | `timeout`、`detail` | 类似 ES `ping` 后再取版本；用于确认客户端能连到 Milvus 服务 | 阶段三已输出版本，作为脚本启动时的轻量连通性检查 |
| `list_collections(...)` | 无 | 列出当前 database 下已有 collection，也可作为最小健康检查 | 阶段三已输出集合清单，对应关系型数据库里查看表清单 |
| `has_collection(...)` | `collection_name`、`timeout` | 判断目标 collection 是否存在 | 示例和模板已用于避免重复创建或误删 |
| `describe_collection(...)` | `collection_name`、`timeout` | 查看 collection schema、字段、主键、向量维度、dynamic field、consistency 等信息 | 阶段三和阶段七已演示，类似关系型数据库的 `DESC table` |
| `get_collection_stats(...)` | `collection_name`、`timeout` | 查看 collection 行数、segment 等统计信息，具体键会受版本和部署模式影响 | 阶段三观察写入前后行数；阶段九演示 flush/compact 后观察 stats |
| `create_database(...)` / `drop_database(...)` / `list_databases(...)` / `use_database(...)` | `db_name`、`properties`、`timeout` | 多 database 隔离；适合多环境、多租户或管理后台 | README 说明 `db_name`，示例保持单 DB，避免增加学习噪声 |
| `rename_collection(...)` | `old_name`、`new_name`、`target_db` | 重命名 collection | 生产发布更推荐 alias 切换，本教程不作为主线 |
| `truncate_collection(...)` | `collection_name`、`timeout` | 清空 collection 数据但保留 schema/index | 破坏性强，生产应放到受控运维命令 |
| `add_collection_field(...)` / `alter_collection_field(...)` / `drop_collection_field(...)` | `collection_name`、`field_name`、`data_type`、`field_params`、`timeout` | schema 演进相关操作 | 生产更推荐新 collection + alias 发布，避免在线结构变更风险 |
| `list_indexes(...)` / `describe_index(...)` / `drop_index(...)` | `collection_name`、`field_name`、`index_name` | 查看或删除索引；排查 `index_type`、`metric_type`、`params` 是否符合预期 | 阶段六已演示 `list_indexes/describe_index`，不展开删除索引专项 |
| `list_aliases(...)` / `describe_alias(...)` | `collection_name`、`alias`、`timeout` | 查看 alias 当前指向和别名列表 | 阶段七已讲 alias 切换，并输出 `describe_alias` 确认当前指向 |
| `list_partitions(...)` / `has_partition(...)` / `get_partition_stats(...)` | `collection_name`、`partition_name`、`timeout` | 查看 partition 列表、存在性和统计信息 | 阶段七演示 partition 生命周期时会观察分区列表、存在性和行数 |
| `load_partitions(...)` / `release_partitions(...)` | `collection_name`、`partition_names`、`timeout` | Standalone 上按 partition 加载或释放查询资源 | 阶段七说明 Lite 边界，阶段九讲 collection 级 load/release |
| `create_user(...)` / `create_role(...)` / `grant_privilege_v2(...)` | `user_name`、`role_name`、`privilege`、`collection_name`、`db_name` | 用户、角色和权限管理 | 属于安全/RBAC 专题，本教程只提醒存在 |

## 学习路线总览

你可以按下面顺序学习，而不是按 RAG 业务流程反复理解：

1. **数据边界**：阶段一学习 Milvus 行数据、向量维度和主键约束。
2. **建模 API**：阶段二学习 schema、字段类型、索引参数和 collection 创建。
3. **基础读写 API**：阶段三学习 `insert/upsert/search/query/delete/get`。
4. **可靠性参数**：阶段四学习错误分类、幂等写入和 `consistency_level`。
5. **客户端形态**：阶段五学习同步与异步客户端如何选择。
6. **检索调参**：阶段六学习索引类型、`search_params`、iterator、grouping search。
7. **数据布局和发布**：阶段七学习 partition、partition key 和 alias。
8. **多路召回 API**：阶段八学习 hybrid search、ranker 和 BM25 schema。
9. **服务端能力**：阶段九学习 Standalone 的 load/release、flush/compact、异步建索引和 iterator V2。

## 学习阶段详解

### 阶段一：向量数据协议（01_basics/）

**学什么**：先理解向量库接收的不是“文档”，而是带稳定主键、文本、来源、chunk 序号和 embedding 的行数据。

**为什么在这里**：很多 Milvus 问题不是数据库问题，而是 embedding 维度、NaN、零向量、主键和 metadata 协议没有提前约束。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 1 | `01_vector_protocol.py` | LangChain `Document` 协议、行数据转换、L2 归一化 | 输出的 Milvus row 字段是否完整 |
| 2 | `02_dimension_validation.py` | 维度校验、非法数值、零向量 | 错误是否在客户端边界暴露 |

**关键收获**：知道写入 Milvus 前必须先定义数据协议，而不是直接把任意 dict 塞给 SDK。

### 阶段二：schema 与 index（02_schema_index/）

**学什么**：构造 collection schema、主键、`FLOAT_VECTOR`、标量字段、`AUTOINDEX` 和 `COSINE`。

**为什么在这里**：schema 和 index 是 Milvus 的工程边界。后续插入、搜索、过滤都依赖字段名、字段类型和度量方式。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 3 | `01_build_schema_and_index.py` | `create_schema`、`DataType`、`prepare_index_params` | 字段、维度、索引参数是否符合预期 |
| 4 | `02_collection_name_policy.py` | 集合命名、前缀隔离、清理边界 | 集合名是否始终带 `learning_milvus_` 前缀 |

**关键收获**：能在不连接服务的情况下先审查 schema/index 设计，减少运行时排错成本。

### 阶段三：同步 CRUD 与过滤（03_filter_and_crud/）

**学什么**：用同步 `MilvusClient` 完成真实 collection 创建、写入、搜索、标量过滤、查询和删除。

**为什么在这里**：同步客户端调用链直观，适合建立 Milvus 核心 API 心智模型。异步客户端放到后面，避免一开始同时学习数据库概念和并发概念。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 5 | `01_lite_insert_search.py` | `MilvusClient(uri)`、`get_server_version`、`list_collections`、`describe_collection`、`get_collection_stats`、`upsert(data)`、`search(...)` | 连接版本、集合清单、字段结构、行数和 top hit 是否符合预期 |
| 6 | `02_scalar_filter_query_delete.py` | `search(filter=...)`、`query(filter,output_fields,limit)`、`delete(filter/ids)` | filter 是否限定 source，delete 是否只删目标来源 |

**关键收获**：能用 `MilvusClient` 跑通单机语义搜索闭环，并知道 query 和 search 的差别。

### 阶段四：错误恢复与幂等（04_errors_and_recovery/）

**学什么**：区分参数错误、数据错误、连接错误和可重试错误；用稳定主键和 `upsert` 支持导入任务重跑；理解一致性级别对写后读链路的影响。

**为什么在这里**：批量向量导入经常要失败重跑。如果主键不稳定或盲目 retry，会产生重复数据或隐藏真实错误。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 7 | `01_client_side_errors.py` | `collection_name`、`data`、`dim`、空批次、非法字段 | 哪些错误不应该进入 Milvus |
| 8 | `02_idempotent_upsert.py` | `upsert(data)`、稳定主键、重复执行 | 同一批 upsert 两次后记录数不膨胀 |
| 9 | `03_consistency_levels.py` | `consistency_level="Strong/Bounded/Eventually/Session"` | collection 默认值和单次请求覆盖的区别 |

**关键收获**：能为索引构建任务设计可重跑的数据写入策略，并知道“写完立刻搜不到”要从 flush/load、索引和一致性三个方向排查。

### 阶段五：异步客户端（05_async_client/）

**学什么**：在基础 API 已经掌握后，使用 `AsyncMilvusClient` 的 `async with`、`await`、`asyncio.gather` 和并发上限。

**为什么在这里**：异步客户端适合 FastAPI、异步 worker、批量查询等场景，但它不改变 Milvus 的数据模型。先学同步 API，再学习异步生命周期，认知负担更低。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 10 | `01_async_search_many.py` | `AsyncMilvusClient.search(...)`、`asyncio.gather`、并发上限 | 批量搜索是否有明确并发上限 |
| 11 | `02_async_lifecycle_policy.py` | `AsyncMilvusClient(uri)`、`close()`、服务启动/关闭 | 在线检索复用同一个异步客户端 |

**关键收获**：能把 Milvus 检索接入异步服务，同时避免每个请求新建连接或无限并发。

### 阶段六：索引与搜索参数（06_index_and_search_params/）

**学什么**：系统认识 Milvus 常见索引类型、构建参数、搜索参数、iterator 分批读取和 grouping search 去重。

**为什么在这里**：基础 CRUD 只解决“能用”，生产检索还需要理解不同索引的召回、延迟、内存和磁盘取舍。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 12 | `01_index_catalog.py` | `index_type`、`metric_type`、`params` 参数目录 | 每种索引适合什么场景 |
| 13 | `02_build_multiple_index_params.py` | `prepare_index_params()`、多次 `add_index(field_name=...)`、`list_indexes`、`describe_index` | dense/title/sparse 字段如何分别配置，服务端实际索引是否符合预期 |
| 14 | `03_range_search_params.py` | `search_params={"params": {"nprobe","ef","radius","range_filter"}}` | 搜索参数如何影响召回和延迟 |
| 15 | `04_iterators_large_results.py` | `query_iterator(batch_size,limit)`、`search_iterator(batch_size,limit)`、`close()` | 大结果集为什么要分批读取并显式 close |
| 16 | `05_grouping_search.py` | `group_by_field`、`group_size`、`strict_group_size` | 同一文档多 chunk 命中时如何按字段去重 |

**关键收获**：能根据场景说清楚为什么先用 `AUTOINDEX`，何时评估 `IVF_FLAT`、`HNSW`、`DISKANN`、`SCANN` 或稀疏索引，也能处理大结果集分批读取和字段级分组去重。

### 阶段七：partition 与 alias（07_partitions_aliases/）

**学什么**：手动 partition 的粗粒度隔离、partition key 的自动路由，以及 alias 支持蓝绿索引切换。

**为什么在这里**：collection 进入服务化使用后，经常需要数据布局、版本切换和回滚能力。partition 与 alias 是 Milvus 自己提供的两类边界。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 17 | `01_partition_lifecycle.py` | `create_partition`、`list_partitions`、`has_partition`、`get_partition_stats`、`release_collection`、`drop_partition`、`partition_names` | partition_names 和 scalar filter 的职责差别 |
| 18 | `02_alias_switching.py` | `create_alias`、`list_aliases`、`describe_alias`、`alter_alias`、`drop_alias` | 在线服务为什么应查询 alias，以及如何确认 alias 当前指向 |
| 19 | `03_partition_key.py` | `schema.add_field(is_partition_key=True)`、partition key 自动路由 | partition key 和手动 partition 的适用边界 |

**关键收获**：能设计 collection 版本切换流程，避免在生产服务里直接绑定物理 collection 名，也能区分手动 partition、partition key 和 scalar filter。

### 阶段八：混合检索（08_hybrid_search/）

**学什么**：dense 向量、sparse 向量、BM25 和 hybrid rerank 的 API 结构。

**为什么在这里**：掌握单路 `search` 后，再学习多向量字段、多路请求和 ranker 融合，才能看懂 hybrid search 的请求结构。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 20 | `01_hybrid_request.py` | `AnnSearchRequest(data,anns_field,param,limit,filter)`、`RRFRanker(k)`、`WeightedRanker(*weights,norm_score=True)` | 每个向量字段一个请求，再用 ranker 融合 |
| 21 | `02_bm25_schema.py` | `SPARSE_FLOAT_VECTOR`、`FunctionType.BM25`、`enable_analyzer`、Function 输入/输出字段 | BM25 必须在 schema 创建期设计 |

**关键收获**：能看懂 Milvus hybrid search 的请求结构，并知道 BM25 schema 不是查询时临时参数。

### 阶段九：Standalone 运维（09_standalone_ops/）

**学什么**：真实 Milvus Standalone 才有的加载生命周期、segment 管理和异步 DDL。

**为什么在这里**：前八个阶段用 Milvus Lite 建立心智模型，Lite 把很多服务端概念隐藏了。真正上生产用 Standalone 时，load/release、flush/compact、异步建索引这些是绕不开的运维基本功。本阶段必须连真实 Standalone（`MILVUS_URI=http://localhost:19530`），Lite 模式下示例会提示并跳过。

| 顺序 | 文件 | 核心概念 | 观察重点 |
|------|------|----------|----------|
| 22 | `01_load_release_lifecycle.py` | `load_collection`、`release_collection`、`get_load_state` | release 后搜索报 collection not loaded，load 后恢复 |
| 23 | `02_flush_compact_stats.py` | `flush`、`compact`、`get_collection_stats` | flush 落盘成 sealed segment，删除后 compact 回收 |
| 24 | `03_async_index_build.py` | `AsyncMilvusClient` 异步建集合+索引 | 这条路径在 Lite 触发未实现 RPC，Standalone 才支持 |
| 25 | `04_search_iterator_v2.py` | `search_iterator`、`batch_size`、`limit`、`close` | Lite 回退 V1，Standalone 完整 V2，分批拉取大结果 |

**关键收获**：理解“Lite 上能搜不代表 Standalone 上能搜”——数据必须 load 进 query node 内存；知道 flush/compact 与对象存储 segment 的关系；能用异步客户端在服务端并发初始化集合。

## 模板与后续阅读

阅读 `templates/`：

1. `settings.py`：统一配置和集合命名。
2. `vector_utils.py`：数据协议和向量校验。
3. `sync_repository.py`：同步脚本/离线任务骨架。
4. `async_repository.py`：异步服务/worker 骨架。
5. `index_catalog.py`：索引选型和参数目录。
