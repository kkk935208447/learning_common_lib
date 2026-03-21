# AgenticRAG DeepSearch 最小可执行 Demo

这个目录是 `用户AgenticRAG检索` 模块的可运行代码版本。

它保留了完整链路：

1. `POST /api/v1/search` 异步提交任务
2. `GlobalGraph` 执行 `Intake -> Planner -> Clarify -> Scheduler -> Executor -> StepGate -> Replan / Finalize`
3. `SubtaskGraph` 执行 `Rewrite -> Retrieval(Vector+ES) -> Evaluate -> Draft -> Verify -> Escalate`
4. `Celery` 执行 `orchestrate_jobs / subtask_jobs / persist_jobs / maintenance_jobs`
5. Redis 承担 checkpoint、`L2` 子任务工作记忆、`L3-Control` 热缓存、`L3-Evidence` 热池与 SSE 回放辅助
6. `task_events + SSE` 负责实时进度和 `Last-Event-ID` 回放

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
7. API / SSE 的时间戳统一以 UTC 输出，格式带尾缀 `Z`

说明：

1. 普通 Redis 也可以运行当前 demo。
2. 当前 demo 只依赖普通 Redis 的键值与列表能力，不要求 RediSearch / Redis Stack 扩展。

## 真实前置条件

这个 demo 不是通过 HTTP 去访问上游数据库管理 demo，而是直接复用它的本地代码和运行产物。

运行前需要满足：

1. `../../实现AgenticRAG数据库管理/最小可执行demo` 目录存在。
2. DeepSearch 和上游 demo 连接到同一个 MySQL 实例。
3. 上游 demo 已经初始化并 seed 活动知识。
4. 上游 `.runtime/vector_store`、`.runtime/search_store` 和对象存储布局可读。
5. 当前最小 demo 只支持 `kb_code=default`。
6. `scope_json` 目前只支持 `document_ids`、`external_doc_keys`、`version_ids` 三个键；传入其他键或错误类型会返回 `422`。

## 当前目录

以下命令默认都先进入本目录执行：

```bash
cd src/learning_common_lib/案例/用户AgenticRAG检索/最小可执行demo
```

阅读源码时可以忽略 `.runtime/`、`__pycache__/` 和 `celerybeat-schedule.db` 这类运行产物，它们不属于教程主线。

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

1. [api/app.py](./api/app.py)：FastAPI 应用本体
2. [workers/celery_app.py](./workers/celery_app.py)：Celery 应用本体
3. [infrastructure/settings.py](./infrastructure/settings.py)：运行时配置
4. [infrastructure/database.py](./infrastructure/database.py)：数据库连接与 session 工厂
5. [infrastructure/runtime_bundle.py](./infrastructure/runtime_bundle.py)：运行时装配与服务组合
6. [infrastructure/factories.py](./infrastructure/factories.py)：适配器工厂与测试注入入口
7. [application/errors.py](./application/errors.py)：应用异常
8. [scripts/demo/](./scripts/demo)
9. [scripts/setup/](./scripts/setup)
10. [test/](./test)

## 代码阅读顺序

如果你是来理解架构，而不是直接启动，建议按下面顺序阅读：

1. `domain/contracts.py`
2. `domain/enums.py`
3. `domain/dag.py`
4. `domain/clarify_rules.py`
5. `domain/state_machine.py`
6. `application/plan_service.py`
7. `application/search_command_service.py`
8. `application/run_service.py`
9. `application/global_graph_service.py`
10. `application/subtask_graph_service.py`
11. `application/evidence_service.py`
12. `application/progress_service.py`
13. `application/session_service.py`
14. `application/maintenance_service.py`
15. `application/errors.py`
16. `infrastructure/settings.py`
17. `infrastructure/database.py`
18. `infrastructure/runtime_bundle.py`
19. `api/routes.py`
20. `workers/orchestrate_tasks.py`
21. `workers/subtask_tasks.py`
22. `workers/celery_app.py`

理解建议：

1. 先看 `domain/*`，先建立契约、状态字段和 DAG 结构的心智模型。
2. 再看 `application/plan_service.py + search_command_service.py + run_service.py`，理解请求进入后如何变成 plan、subtask 和 dispatch。
3. 然后看 `global_graph_service.py + subtask_graph_service.py + evidence_service.py`，把全局闭环和子任务闭环串起来。
4. 最后再看 `progress/session/maintenance + infrastructure/* + workers/*`，理解 SSE、恢复补偿和运行时装配。

## 破坏性说明

下面这些脚本会重建或覆写 demo 数据，不适合在你想保留现有样例数据时直接执行：

1. `scripts/setup/init_db.py`
2. `scripts/demo/demo_flow.py`
3. `test/setup/test_prepare_upstream.py`
4. `test/setup/test_prepare_control_plane.py`
5. `test/offline/run_all.py`

## 初始化

### 初始化上游知识投影与测试 fixture

```bash
uv run python test/setup/test_prepare_upstream.py
```

### 初始化 DeepSearch 控制面

```bash
uv run python test/setup/test_prepare_control_plane.py
```

说明：

1. `test/setup/test_prepare_upstream.py` 会重建上游数据库管理 demo 的表，并按 `test/fixtures/knowledge/` 中的数据重新 seed 活动知识。
2. `test/setup/test_prepare_control_plane.py` 会重建当前 DeepSearch 控制面表。
3. FastAPI / Celery 启动流程不会自动建表；如果控制面表不存在，必须先执行初始化脚本。
4. 如果你只想验证 API / worker，不要在已有样例数据上反复执行这些准备脚本。

## 启动方式

### 方式 1：直接运行 API 入口

启动 API：

```bash
DEEPSEARCH_DEMO_CELERY_EAGER=0 uv run python api/app.py
```

### 方式 2：使用 Celery CLI

启动 Worker。为了让场景脚本的虚拟 LLM / 检索序列严格可复现，建议固定 `--concurrency=1`：

```bash
DEEPSEARCH_DEMO_CELERY_EAGER=0 uv run celery -A workers.celery_app:celery_app worker -Q orchestrate_jobs,subtask_jobs,persist_jobs,maintenance_jobs --concurrency=1 -l INFO
```

启动 Beat：

```bash
DEEPSEARCH_DEMO_CELERY_EAGER=0 uv run celery -A workers.celery_app:celery_app beat -l INFO
```

清理残留队列消息：

```bash
uv run celery -A workers.celery_app:celery_app purge -f
```

## 演示脚本

### 1. 单进程 eager 演示

这个脚本不依赖外部 worker / beat / FastAPI，但仍然依赖 MySQL、Redis 和上游知识库 demo：

```bash
uv run python scripts/demo/demo_flow.py
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
uv run python scripts/demo/client_demo.py
```

如果 API 不是默认端口 `8092`，可以指定：

```bash
DEEPSEARCH_DEMO_API_PORT=8094 uv run python scripts/demo/client_demo.py
```

说明：

1. 这个脚本只演示 `submit + immediate snapshot`。
2. 它不会轮询到终态，也不会演示 SSE。
3. 如果快照里看到 `PENDING / PLANNING / EXECUTING`，这通常是正常现象，不表示 API 异常。

### 3. 离线提交演示

这个脚本不经过 FastAPI，直接通过服务层写 MySQL 并把任务投递到 Celery。要求 worker 已启动：

```bash
uv run python scripts/demo/offline_submit_demo.py
```

当前预期：

1. `submit` 返回 `request_id`
2. 当前示例查询通常会从 `PENDING` 进入 `COMPLETED`
3. 一般流程也可能进入 `WAITING_CLARIFICATION`
4. 最终快照和 HTTP 提交的输出结构一致

## 测试目录

测试相关脚本已经统一迁到 [test/](./test) 目录。

目录约定：

1. `test/setup/`：初始化脚本
2. `test/offline/`：离线回归脚本
3. `test/contract/`：HTTP 契约回归脚本
4. `test/support/`：共享 runner、场景适配器、准备逻辑和断言逻辑
5. `test/fixtures/knowledge/`：上游知识库测试数据
6. `test/fixtures/scenarios/`：场景定义，控制虚拟 LLM、检索返回、故障注入和预期结果
7. `test/results/`：测试执行输出目录

当前内置的关键场景：

1. `offline_happy_path`
2. `offline_preplan_clarify`
3. `offline_step_gate_clarify`
4. `offline_subtask_retry`
5. `offline_replan_flow`
6. `checkpoint_resume_recovery`

虚拟 LLM 说明：

1. 默认仍兼容当前 demo 的 `MockLLM`
2. 场景测试可切换到 LangChain 的 `FakeListLLM`
3. 场景脚本通过 `DEEPSEARCH_DEMO_TEST_SCENARIO_ID` 注入 worker / beat / API 进程

测试运行注意事项：

1. 除 `test_checkpoint_degraded_recovery.py` 以外，其余脚本默认都使用你当前 `DEEPSEARCH_DEMO_REDIS_*` 配置去连接真实 Redis；如果 Redis 密码不是默认值，先显式导出环境变量。
2. `test_checkpoint_degraded_recovery.py` 会在脚本进程内临时把 `DEEPSEARCH_DEMO_REDIS_PASSWORD` 改成错误值，用来验证 checkpoint 会自动降级到 memory backend。这个脚本打印 `backend=memory`、`degraded=true` 才是成功，不表示你的线上配置有问题。
3. `test/offline/*.py` 里的大多数脚本都假设 `worker + beat` 已经运行；如果只启动了 API，没有启动 worker，任务会长时间停在 `PENDING / WAITING_SUBTASKS`。
4. `test/offline/run_all.py` 会先重建上游数据和当前控制面表，然后再逐条执行离线脚本；它适合回归，不适合保留现场数据。
5. `test/support/production_stack_suite.py` 会自己执行初始化、清队列、拉起 `worker + beat + api`，并在结束后关闭进程。运行它之前不要再手工保留一套同目录下的 API / worker 进程，避免日志和队列互相干扰。
6. `test/support/production_stack_suite.py` 默认使用端口 `8097`，而日常 `api/app.py` 默认端口是 `8092`；如果你自己改过环境变量，先确认不会冲突。
7. 如果你在受限环境中运行，建议统一加上 `UV_CACHE_DIR=/tmp/uv-cache`，避免 `uv` 尝试写用户目录缓存失败。

## 推荐串行测试步骤

### 1. 准备数据

```bash
uv run python test/setup/test_prepare_upstream.py
uv run python test/setup/test_prepare_control_plane.py
```

补充说明：

1. 这两条脚本会清空并重建表，执行前先确认不需要保留当前 demo 数据。
2. `test_prepare_upstream.py` 只准备上游知识和投影，不会启动当前 deepsearch 的 worker。
3. 如果你希望完全复现仓库内置回归结果，建议在这一步之前先执行一次 `uv run celery -A workers.celery_app:celery_app purge -f` 清空残留消息。

### 2. 启动 Celery CLI 进程

离线测试和服务测试都使用相同的 Celery 运行方式。`offline` 只是绕过 FastAPI，不绕过 Celery。

启动 worker：

```bash
DEEPSEARCH_DEMO_CELERY_EAGER=0 uv run celery -A workers.celery_app:celery_app worker -Q orchestrate_jobs,subtask_jobs,persist_jobs,maintenance_jobs --concurrency=1 -l INFO
```

启动 beat：

```bash
DEEPSEARCH_DEMO_CELERY_EAGER=0 uv run celery -A workers.celery_app:celery_app beat -l INFO
```

运行建议：

1. `worker` 建议保留 `--concurrency=1`，这样场景脚本里的 scripted retrieval / FakeListLLM 顺序最稳定，回归结果最好复现。
2. `beat` 会周期性投递 `apply_clarify_defaults / reap_stuck_runs / recover_orchestration_gaps / rebuild_runtime_cache` 四类维护任务；测试期间看到这些日志属于正常现象。
3. 如果你在一次完整回归里会多次重建数据，建议每轮开始前都清一次队列，避免上一轮残留消息进入新表数据。

### 3. 逐条执行离线功能测试

这些脚本不经过 FastAPI，但要求 `worker + beat` 已经启动：

```bash
uv run python test/offline/test_offline_happy_path.py
uv run python test/offline/test_preplan_clarify.py
uv run python test/offline/test_step_gate_clarify.py
uv run python test/offline/test_subtask_retry.py
uv run python test/offline/test_replan_flow.py
uv run python test/offline/test_stale_result_fencing.py
uv run python test/offline/test_dispatch_gap_recovery.py
uv run python test/offline/test_runtime_cache_rebuild.py
uv run python test/offline/test_checkpoint_degraded_recovery.py
uv run python test/offline/test_checkpoint_resume_recovery.py
uv run python test/offline/test_fallback_partial_result.py
uv run python test/offline/test_invalid_citation_filter.py
```

执行注意事项：

1. 这些脚本全部是单次执行、标准输出 JSON；适合直接在终端串行跑，也适合被外层 CI / shell 包裹。
2. `test_checkpoint_degraded_recovery.py` 不依赖 worker / beat，它只验证构建 graph service 时的 checkpoint 降级行为。
3. `test_checkpoint_resume_recovery.py` 依赖真实 Redis checkpointer；它会先人为制造一个“planner 已执行但 graph 尚未继续”的 checkpoint，再通过 maintenance 恢复流程验证系统会从 checkpoint 的 `next` 节点继续，而不是重新从 MySQL 推断入口。
4. `test_replan_flow.py` 当前预期允许 `DEGRADED`，因为 demo 里 planner 模板相对稳定，最终通常会命中 `REPLAN_LOOP_DETECTED` 安全收口。
5. `test_dispatch_gap_recovery.py`、`test_runtime_cache_rebuild.py`、`test_checkpoint_resume_recovery.py` 都会主动构造恢复场景，执行时看到 maintenance 相关事件数增加是正常的。

### 4. 启动 FastAPI，再执行服务契约测试

启动 API：

```bash
DEEPSEARCH_DEMO_CELERY_EAGER=0 uv run python api/app.py
```

执行服务测试：

```bash
uv run python test/contract/test_service_contract.py
```

补充说明：

1. 这个脚本默认连接 `http://127.0.0.1:8092`；如果你改了 `DEEPSEARCH_DEMO_API_PORT`，要先把相同端口传给测试脚本所在进程。
2. 该脚本不只检查 HTTP 状态码，还会检查 `SSE /events` 的事件序列、`Last-Event-ID` 回放、Clarify 冲突、heartbeat 负载和 UTC 时间序列化。
3. 当前 SSE 帧格式约定为：
   帧头使用 `id:` 和 `event:`。
   `data:` 只包含业务负载，也就是 `request_id / status / message / ts / plan_version / subtask_code / execution_id` 等字段，不再重复携带顶层 `id/event`。

### 5. 使用总串行脚本跑完整离线链路

如果你已经启动好 `worker + beat`，也可以用下面的脚本串行执行全部离线测试：

```bash
uv run python test/offline/run_all.py
```

补充说明：

1. 这个脚本会先自动执行 `test_prepare_upstream.py` 和 `test_prepare_control_plane.py`，然后按固定顺序调用各个离线脚本。
2. 它要求外部 `worker + beat` 已经启动；它自己不会负责拉起 Celery 进程。
3. 如果你想要“一条命令自己拉起进程并跑完整服务/离线套件”，使用 `test/support/production_stack_suite.py` 更合适。

## 每个测试脚本覆盖的行为

1. `test/offline/test_offline_happy_path.py`
说明：标准离线提交、规划、分发、汇总闭环

2. `test/offline/test_preplan_clarify.py`
说明：`PREPLAN` Clarify 请求、回复、恢复

3. `test/offline/test_step_gate_clarify.py`
说明：`STEP_GATE` Clarify 与用户口径选择

4. `test/offline/test_subtask_retry.py`
说明：通过场景 fixture 模拟“首次检索证据不足，补检后完成”

5. `test/offline/test_replan_flow.py`
说明：通过场景 fixture 模拟“首次执行失败，进入 Replan 分支”；当前 demo 会因为 planner 模板稳定而命中 `REPLAN_LOOP_DETECTED` 降级收口，但 `task_replanned` 分支可被稳定验证

6. `test/offline/test_stale_result_fencing.py`
说明：验证旧执行结果只会写 `STALE_IGNORED`，不会推进新计划

7. `test/offline/test_dispatch_gap_recovery.py`
说明：验证 `CLAIMED/DISPATCHED` 缺口可由 maintenance 补发

8. `test/offline/test_runtime_cache_rebuild.py`
说明：验证清空 Redis 热缓存后可按 MySQL 重建

9. `test/offline/test_checkpoint_degraded_recovery.py`
说明：验证 checkpoint Redis 不可用时会降级到 memory backend

10. `test/offline/test_checkpoint_resume_recovery.py`
说明：验证 maintenance 恢复时会优先从现有 checkpoint 的 `next` 节点继续执行，而不是简单按 MySQL 状态重新推断入口

11. `test/offline/test_fallback_partial_result.py`
说明：验证降级输出仍保留部分结果、引用和不确定性说明

12. `test/offline/test_invalid_citation_filter.py`
说明：验证最终引用会过滤掉不属于证据卡集合的 citation

13. `test/contract/test_service_contract.py`
说明：验证 HTTP + SSE 对外契约，包括 `Last-Event-ID`、Clarify、heartbeat 和服务端口径

14. `test/support/production_stack_suite.py`
说明：一键拉起完整生产式栈并执行服务契约 + 离线恢复测试总套件，适合做最终验收

## 场景与数据说明

### 知识库数据

`test/fixtures/knowledge/default_documents.json` 是上游 seed 清单：

1. `travel_policy_v1.txt`
说明：当前活动版差旅报销制度，包含住宿上限和高铁审批变化

2. `travel_policy_compare.txt`
说明：补充说明，提供“对比上一版”的变化摘要

### 场景定义

`test/fixtures/scenarios/` 中每个 JSON 固定包含：

1. `id`
2. `mode`
3. `input`
4. `llm_backend`
5. `llm_script`
6. `retrieval_script`
7. `fault_injection`
8. `expected`

当前重点场景：

1. `offline_subtask_retry.json`
说明：首次检索固定返回空结果，只有出现“补充检索”时才返回有效 evidence，用来保证本地补检分支被真实走到

2. `offline_replan_flow.json`
说明：前 4 轮检索固定失败，用来保证 `task_replanned` 分支被走到；当前 demo 的 planner 模板固定，后续会命中 `REPLAN_LOOP_DETECTED`

场景与脚本的关系说明：

1. `offline_happy_path / offline_preplan_clarify / offline_step_gate_clarify / offline_subtask_retry / offline_replan_flow` 这 5 个脚本会通过 `setup_test_env(scenario_id=...)` 自动激活对应场景。
2. `test_stale_result_fencing.py`、`test_dispatch_gap_recovery.py`、`test_runtime_cache_rebuild.py`、`test_checkpoint_resume_recovery.py`、`test_fallback_partial_result.py`、`test_invalid_citation_filter.py` 主要通过直接构造数据库状态来验证恢复和收口逻辑，不依赖 `fixtures/scenarios/*.json`。

## 测试结果与日志

1. 每个脚本默认把结构化结果打印成 JSON，便于 CI 或人工复制保存
2. `test/support/production_stack_suite.py` 会把 `worker / beat / api` 的日志写到 `.runtime/integration_logs/`
3. 如果你只手工运行单条离线脚本，常规进度与错误主要看你当前终端里的 worker / beat 输出
4. `test/results/` 预留给后续扩展的结果落盘；当前场景切换信息会写入 `test/results/active_scenario.json`

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

SSE 负载补充约定：

1. `event: heartbeat` 时，`data` 只包含 `request_id` 与 `ts`。
2. 非 heartbeat 事件的 `data` 至少包含 `request_id`、`ts`，通常还会带 `status`、`message`，以及可选的 `plan_version / subtask_code / execution_id`。
3. Clarify 相关事件里，`clarification_requested` 的 `data` 会附带完整 `clarification_request`，而 `GET /search/{request_id}` 在 `WAITING_CLARIFICATION` 下也会返回相同结构。

## 当前已验证的能力

1. eager 模式下，`scripts/demo/demo_flow.py` 可直接跑到 `COMPLETED`
2. 非 eager 模式下，`worker + beat + MySQL + Redis` 支撑的离线功能测试已可逐条执行
3. 非 eager 模式下，`FastAPI + worker + beat + MySQL + Redis` 的服务契约测试已可独立执行
4. `test/fixtures/scenarios/` 已支持通过虚拟 LLM / 检索脚本模拟补检、Replan、Clarify 等支路
5. LangChain `FakeListLLM` 已可作为场景测试后端之一
6. maintenance 恢复链已经验证到两类恢复来源：
说明：可从 MySQL 控制面热缓存重建，也可在存在 pending checkpoint 时直接从 checkpoint 的 `next` 节点恢复 graph 执行现场

## 常见失败

1. `uv run` 报依赖或缓存错误：先执行 `uv sync`，必要时更换 `UV_CACHE_DIR`
2. MySQL 认证失败：检查 `DEEPSEARCH_DEMO_MYSQL_*` 与 `MIN_RAG_*` 环境变量
3. Redis 认证或连接失败：检查 `DEEPSEARCH_DEMO_REDIS_*` 环境变量
4. 表不存在：先执行上游 `init_db.py`、`scripts/setup/seed_demo_kb.py` 和当前目录 `scripts/setup/init_db.py`
5. 离线测试脚本长时间停在非终态：先确认 `worker + beat` 已用 CLI 正常启动
6. 服务测试脚本无法连接：先确认 `api/app.py` 已启动并通过 `/api/v1/health`
7. `test_checkpoint_degraded_recovery.py` 输出 `backend=memory`：这是脚本预期，不需要把 Redis 配置改回去；脚本退出后环境变量不会污染其他进程
8. `test_checkpoint_resume_recovery.py` 没进入 `WAITING_CLARIFICATION`：优先检查 Redis checkpoint 是否真的可写，以及有没有误把 worker 跑成 `DEEPSEARCH_DEMO_CELERY_EAGER=1`

## 当前限制

1. 检索通道只启用 `Vector + ES`
2. Clarify 只支持单选
3. `KnowledgeProjectionReader` 当前只支持 `document_ids / external_doc_keys / version_ids`
4. `FileVectorReader` 与 `FileSearchReader` 仍然是 demo 级实现，不是生产级召回
5. checkpoint 当前用于线程级热状态续跑与 Redis 热副本辅助；任务恢复的真相仍然以 MySQL 控制面状态为准
6. `ST-003` 虽然已经会做结构化汇总，但仍然基于 mock LLM 和 mock scoring，不是生产级推理质量
