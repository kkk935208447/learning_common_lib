# AgenticRAG DeepSearch 最小可执行 Demo

这个目录是 `用户AgenticRAG检索` 模块的可运行代码版本。

它保留了完整链路：

1. `POST /api/v1/search` 异步提交任务
2. `GlobalGraph` 执行 `Intake -> Planner -> Clarify -> Scheduler -> Executor -> StepGate -> Replan / Finalize`
3. `SubtaskGraph` 执行 `Rewrite -> Retrieval(Vector+ES) -> Evaluate -> Draft -> Verify -> Escalate`
4. `Celery` 执行 `orchestrate_jobs / subtask_jobs / persist_jobs / maintenance_jobs`
5. `task_events + SSE` 负责实时进度和 `Last-Event-ID` 回放

## 环境

1. Python 3.11
2. MySQL 8.0+
3. Redis 7.x
4. 同仓库内的上游数据库管理 demo 目录存在，并且其 MySQL / `.runtime` 投影可读

默认配置：

1. DeepSearch 使用 `DEEPSEARCH_DEMO_` 前缀环境变量
2. 上游数据库管理 demo 使用 `MIN_RAG_` 前缀环境变量
3. DeepSearch 默认端口 `8092`
4. DeepSearch 默认 MySQL: `127.0.0.1:3306`，账号 `root`，密码 `123456`
5. DeepSearch 默认 Redis: `127.0.0.1:6379`，密码 `123456`
6. DeepSearch 表名前缀 `rag_search_demo`

说明：

1. 普通 Redis 也可以运行当前 demo。
2. 如果 Redis 缺少 RediSearch / Redis Stack 能力，checkpoint 会自动降级，不影响最小链路演示。

## 真实前置条件

这个 demo 不是通过 HTTP 去访问上游数据库管理 demo，而是直接复用它的本地代码和运行产物。

运行前需要满足：

1. `../../实现AgenticRAG数据库管理/最小可执行demo` 目录存在。
2. DeepSearch 和上游 demo 连接到同一个 MySQL 实例。
3. 上游 demo 已经初始化并 seed 活动知识。
4. 上游 `.runtime/vector_store`、`.runtime/search_store` 和对象存储布局可读。
5. 当前最小 demo 只支持 `kb_code=default`。
6. `scope_json` 目前只支持 `document_ids`、`external_doc_keys`、`version_ids` 三个键，其他过滤条件会被忽略。

## 当前目录

以下命令默认都先进入本目录执行：

```bash
cd src/learning_common_lib/案例/用户AgenticRAG检索/最小可执行demo
```

## 快速开始

先同步依赖：

```bash
uv sync
```

如果你需要覆盖默认连接参数，常见环境变量如下：

```bash
export DEEPSEARCH_DEMO_MYSQL_HOST=127.0.0.1
export DEEPSEARCH_DEMO_MYSQL_PORT=3306
export DEEPSEARCH_DEMO_MYSQL_USER=root
export DEEPSEARCH_DEMO_MYSQL_PASSWORD=123456
export DEEPSEARCH_DEMO_REDIS_HOST=127.0.0.1
export DEEPSEARCH_DEMO_REDIS_PORT=6379
export DEEPSEARCH_DEMO_REDIS_PASSWORD=123456
```

如果你在离线或受限网络环境中运行 `uv run`，可以额外指定缓存目录：

```bash
export UV_CACHE_DIR=/tmp/uv-cache-deepsearch
```

## 目录里的关键入口

1. [api.py](./api.py)
2. [celery_app.py](./celery_app.py)
3. [worker_main.py](./worker_main.py)
4. [beat_main.py](./beat_main.py)
5. [demo_flow.py](./demo_flow.py)
6. [offline_submit_demo.py](./offline_submit_demo.py)
7. [client_demo.py](./client_demo.py)
8. [integration_test_production_stack.py](./integration_test_production_stack.py)

## 代码阅读顺序

如果你是来理解架构，而不是直接启动，建议按下面顺序阅读：

1. `service_runtime.py`
2. `bootstrap.py`
3. `domain/contracts.py`
4. `domain/dag_templates.py`
5. `domain/clarify_rules.py`
6. `application/plan_service.py`
7. `api/routes.py`
8. `application/search_command_service.py`
9. `application/run_service.py`
10. `application/global_graph_service.py`
11. `application/subtask_graph_service.py`
12. `application/evidence_service.py`
13. `workers/orchestrate_tasks.py`
14. `workers/subtask_tasks.py`

理解建议：

1. 先看 `service_runtime.py + bootstrap.py`，明确依赖是如何组装的。
2. 再看 `domain/* + plan_service.py`，先建立术语和计划生成的心智模型。
3. 然后看 `routes.py + search_command_service.py + run_service.py`，理解请求进入和控制面规则。
4. 最后看 `global_graph_service.py + subtask_graph_service.py + workers/*`，把图编排和异步包装串起来。

## 破坏性说明

下面这些脚本会重建或覆写 demo 数据，不适合在你想保留现有样例数据时直接执行：

1. `init_db.py`
2. `demo_flow.py`
3. `integration_test_production_stack.py`

## 初始化

### 初始化上游知识投影

```bash
uv run python ../../实现AgenticRAG数据库管理/最小可执行demo/init_db.py
MIN_RAG_CELERY_EAGER=1 uv run python seed_demo_kb.py
```

### 初始化 DeepSearch 控制面

```bash
uv run python init_db.py
```

说明：

1. `init_db.py` 会先 `drop_all` 再 `create_all`。
2. 如果你只想验证 API / worker，不要在已有样例数据上反复执行它。

## 启动方式

### 方式 1：直接运行 py 文件

启动 API：

```bash
DEEPSEARCH_DEMO_CELERY_EAGER=0 uv run python api.py
```

启动 Worker：

```bash
DEEPSEARCH_DEMO_CELERY_EAGER=0 uv run python worker_main.py
```

启动 Beat：

```bash
DEEPSEARCH_DEMO_CELERY_EAGER=0 uv run python beat_main.py
```

### 方式 2：使用 Celery CLI

启动 Worker：

```bash
DEEPSEARCH_DEMO_CELERY_EAGER=0 uv run celery -A celery_app:celery_app worker -Q orchestrate_jobs,subtask_jobs,persist_jobs,maintenance_jobs -l INFO
```

启动 Beat：

```bash
DEEPSEARCH_DEMO_CELERY_EAGER=0 uv run celery -A celery_app:celery_app beat -l INFO
```

清理残留队列消息：

```bash
uv run celery -A celery_app:celery_app purge -f
```

## 演示与测试脚本

### 1. 单进程 eager 演示

这个脚本不依赖外部 worker / beat / FastAPI，但仍然依赖 MySQL、Redis 和上游知识库 demo：

```bash
uv run python demo_flow.py
```

额外说明：

1. 这个脚本会调用 `reset_tables()` 并重新 seed 上游活动知识。
2. 它更适合联调，不适合作为保留现场数据时的只读演示。

当前预期：

1. 请求会直接跑到终态
2. 样例查询会得到 `COMPLETED`
3. 最终快照带 `final_answer`、`final_citations`、`coverage_summary`

### 2. HTTP 客户端演示

要求 API 已启动：

```bash
uv run python client_demo.py
```

如果 API 不是默认端口 `8092`，可以指定：

```bash
DEEPSEARCH_DEMO_API_PORT=8094 uv run python client_demo.py
```

说明：

1. 这个脚本只演示 `submit + immediate snapshot`。
2. 它不会轮询到终态，也不会演示 SSE。
3. 如果快照里看到 `PENDING / PLANNING / EXECUTING`，这通常是正常现象，不表示 API 异常。

### 3. 离线提交演示

这个脚本不经过 FastAPI，直接通过服务层写 MySQL 并把任务投递到 Celery。要求 worker 已启动：

```bash
uv run python offline_submit_demo.py
```

当前预期：

1. `submit` 返回 `request_id`
2. 当前示例查询通常会从 `PENDING` 进入 `COMPLETED`
3. 一般流程也可能进入 `WAITING_CLARIFICATION`
4. 最终快照和 HTTP 提交的输出结构一致

### 4. 生产式集成测试总控脚本

这个脚本会自动完成以下动作：

1. 重建上游数据库管理表和 DeepSearch 表
2. seed 上游活动知识
3. 用 `celery` CLI 启动 worker 和 beat
4. 用 `api.py` 启动 FastAPI
5. 跑 4 组自动化检查：
   - HTTP completion
   - SSE sequence + `Last-Event-ID` replay
   - Clarify flow
   - offline submit
6. 输出 JSON 汇总，并在结束时自动关闭进程

运行命令：

```bash
uv run python integration_test_production_stack.py
```

说明：

1. 这个脚本会重建 demo 数据，不适合拿现有数据做增量验证。
2. 它固定把 API 端口覆盖到 `8097`。
3. 它会继承外部的 `UV_CACHE_DIR`；如果不传，默认使用 `/tmp/uv-cache`。

脚本成功时会打印类似结果：

```json
{
  "http_completion": {"final_status": "COMPLETED"},
  "sse_sequence": {"event_count": 18},
  "clarify_flow": {"final_status": "COMPLETED"},
  "offline_submit": {"final_status": "COMPLETED"}
}
```

脚本日志会写到：

1. `.runtime/integration_logs/worker.log`
2. `.runtime/integration_logs/beat.log`
3. `.runtime/integration_logs/api.log`

## 对外接口

1. `POST /api/v1/search`
2. `GET /api/v1/search/{request_id}`
3. `GET /api/v1/search/{request_id}/events`
4. `POST /api/v1/search/{request_id}/clarification`

## HTTP 返回格式

所有 HTTP 接口都返回统一 envelope：

```json
{
  "code": "OK",
  "message": "success",
  "data": {}
}
```

当前最常用的约定如下：

1. `POST /api/v1/search` 成功时返回 `200 OK`，`data.status` 当前是 `PENDING`，不是 `PLANNING`。
2. `GET /api/v1/search/{request_id}` 返回任务快照。
3. `POST /api/v1/search/{request_id}/clarification` 成功时返回 `200 OK` 与最新快照。
4. Clarification 冲突场景返回 `409`，响应体是 `{code, message, data: null}`，不会额外附带快照。
5. SSE 断线回放使用 `Last-Event-ID` 请求头，当前实现要求它是整数。

## 当前已验证的能力

1. eager 模式下，`demo_flow.py` 可直接跑到 `COMPLETED`
2. 非 eager 模式下，`FastAPI + Celery worker + Celery beat + MySQL + Redis` 的组合已联调通过
3. 非 eager 模式下，HTTP 提交、离线提交、SSE 事件流、`Last-Event-ID` 回放都已跑通
4. `ST-003` 已不再输出占位文本，而会基于已有 evidence cards 生成结构化 reasoning 汇总
5. 数据面 flush 与控制面 resume 已做顺序屏障，避免非 eager 下先汇总后落库

## 常见失败

1. `uv run` 报依赖或缓存错误：先执行 `uv sync`，必要时更换 `UV_CACHE_DIR`
2. MySQL 认证失败：检查 `DEEPSEARCH_DEMO_MYSQL_*` 与 `MIN_RAG_*` 环境变量
3. Redis 认证或连接失败：检查 `DEEPSEARCH_DEMO_REDIS_*` 环境变量
4. 表不存在：先执行上游 `init_db.py`、`seed_demo_kb.py` 和当前目录 `init_db.py`
5. `client_demo.py` 看到非终态：它只看即时快照，不会自动轮询

## 当前限制

1. 检索通道只启用 `Vector + ES`
2. Clarify 只支持单选
3. `KnowledgeProjectionReader` 当前只支持 `document_ids / external_doc_keys / version_ids`
4. `FileVectorReader` 与 `FileSearchReader` 仍然是 demo 级实现，不是生产级召回
5. 当前全局控制面虽然保留了 `GlobalGraph` 边界，但执行推进仍然是受控手工驱动版本，不是完全依赖 checkpoint 恢复的图运行时
6. `ST-003` 虽然已经会做结构化汇总，但仍然基于 mock LLM 和 mock scoring，不是生产级推理质量
