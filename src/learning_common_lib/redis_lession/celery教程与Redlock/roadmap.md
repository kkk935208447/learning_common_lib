# 学习路线 (Roadmap)

## 前置步骤：验证 Redis 连接

```bash
# 确保 Redis 已启动且密码正确
# Docker 方式:
docker exec <redis容器名> redis-cli -a 123456 ping  # → PONG
# 或 Python 方式:
python -c "import redis; print(redis.Redis(host='localhost', port=6379, password='123456').ping())"

# 确保依赖已安装
uv sync
```

## 阶段一：基础概念（第 1-3 章）

> 目标：理解 Celery 核心模型 — App、Task、Broker、Backend

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 1 | `examples/01_app_and_config/01_celery_hello.py` | 最小 Celery app、broker/worker 架构 | 先跑通两终端模式 |
| 2 | `examples/01_app_and_config/02_config_patterns.py` | 三种配置方式、关键参数 | 知道怎么调参 |
| 3 | `examples/01_app_and_config/03_acks_late_vs_broker_transport.py` | `acks_late` 与 `broker_transport_options` 区别 | 避免把消费语义和 broker 配置混为一谈 |
| 4 | `examples/02_task_definition/01_basic_task.py` | @app.task、bind=True、name | 任务是 Celery 的核心单元 |
| 5 | `examples/02_task_definition/02_serialization.py` | JSON 序列化约束 | 避免生产踩坑 |
| 6 | `examples/03_task_invocation/01_delay_and_apply_async.py` | delay/apply_async/countdown/ETA | 掌握任务发布的所有姿势 |
| 7 | `examples/03_task_invocation/02_signatures.py` | signature/s()/partial/immutable | 工作流编排的基础 |

> 每个示例需要两个终端：一个启动 worker，一个运行脚本。详见各文件顶部 docstring。

## 阶段二：Async Worker 边界（第 4 章）

> 目标：按 `prefork → gevent → custom aio pool` 的顺序理解中间态与终态

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 8 | `examples/04_async_worker_tasks/01_sync_worker_baseline.py` | prefork 基线、producer async vs worker sync | 先建立默认同步模型的参照系 |
| 9 | `examples/04_async_worker_tasks/02_official_greenlet_pools.py` | gevent、cooperative IO、中间态边界 | 说明官方 greenlet pool 与 async def 不是一回事 |
| 10 | `examples/04_async_worker_tasks/03_custom_aio_pool_async_task.py` | `custom aio pool`、最小 `async def task` | 跑通真正的 asyncio worker |
| 11 | `examples/04_async_worker_tasks/04_sync_vs_greenlet_vs_asyncio.py` | 三条路线并排比较 | 把 prefork / greenlet / aio 的边界一次看清 |
| 12 | `examples/04_async_worker_tasks/05_mixed_deployment_patterns.py` | 一个 app 中混合部署三类 worker | 为渐进式迁移提供生产拓扑样板 |

> 这一章是后续 async 化改造的前置章节。建议在进入结果后端、重试、FastAPI 之前先跑完。

## 阶段三：结果与容错（第 5-6 章）

> 目标：在 async-first worker 主线下掌握结果获取与错误恢复策略

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 13 | `examples/05_result_backend/01_async_result.py` | async task + AsyncResult 状态机、get/forget | 在 async-first worker 下继续理解状态语义 |
| 14 | `examples/05_result_backend/02_result_expiry.py` | async task + result_expires 配置 | 防止 Redis 内存爆炸 |
| 15 | `examples/06_error_handling/01_retry_basics.py` | async task + self.retry/max_retries/countdown | 任务失败不可怕，重试才是关键 |
| 16 | `examples/06_error_handling/02_autoretry.py` | async task + autoretry_for/retry_backoff | 自动重试更省心 |

> 每个示例需要两个终端：一个启动 worker，一个运行脚本。详见各文件顶部 docstring。

## 阶段四：生产级特性（第 7-9 章）

> 目标：多队列路由、定时调度、工作流编排

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 17 | `examples/07_routing_and_queues/01_task_queues.py` | 默认队列、自动路由、显式覆盖 | 把逻辑分流和部署分流区分开 |
| 18 | `examples/07_routing_and_queues/02_priority.py` | 优先级队列 | 紧急任务插队 |
| 19 | `examples/08_periodic_tasks/01_celery_beat.py` | beat_schedule/crontab | 定时任务调度 |
| 20 | `examples/08_periodic_tasks/02_dynamic_schedule.py` | 运行时增删定时任务 | 动态调度需求 |
| 21 | `examples/09_workflows/01_chain_and_group.py` | chain/group/错误传播 | 任务编排基础 |
| 22 | `examples/09_workflows/02_chord_and_chunks.py` | chord/chunks | 并行计算 + 汇总 |

> 每个示例需要两个终端：一个启动 worker，一个运行脚本。详见各文件顶部 docstring。

## 阶段五：监控与集成（第 10-11 章）

> 目标：生产监控、FastAPI 集成、分布式锁

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 23 | `examples/10_signals_and_monitoring/01_task_signals.py` | task_prerun/postrun/failure 信号 | 任务生命周期钩子 |
| 24 | `examples/10_signals_and_monitoring/02_flower_and_events.py` | Flower 监控 + 自定义事件 | 生产可观测性 |
| 25 | `examples/11_fastapi_integration/01_fastapi_celery.py` | FastAPI + async-first Celery 触发/轮询 | Web 框架集成 |
| 26 | `examples/11_fastapi_integration/02_distributed_lock.py` | 固定 TTL 锁的短任务/长任务对比 | 先理解为什么长任务会失锁 |
| 27 | `examples/11_fastapi_integration/03_watchdog_lock_with_celery.py` | 无看门狗 vs 有看门狗 | 理解看门狗续期真正解决的问题 |

> 每个示例需要两个终端：一个启动 worker，一个运行脚本。详见各文件顶部 docstring。

## 阶段六：企业模板

> 目标：直接复用到生产项目

| 顺序 | 文件 | 用途 |
|------|------|------|
| 28 | `templates/celery_config.py` | 生产级配置对象 |
| 29 | `templates/celery_app.py` | async-first App 工厂 + producer 侧兼容包装 |
| 30 | `templates/error_handling.py` | 异常层级树 |
| 31 | `templates/task_base.py` | async-first 任务基类 |
| 32 | `templates/distributed_lock.py` | 企业级 python-redis-lock 分布式锁 |
| 33 | `templates/fastapi_celery.py` | async-first worker 的 FastAPI 集成 |

## 建议学习方式

1. 按顺序逐文件运行：先启动 worker，再运行脚本，先看输出再读代码
2. 每章结束后回顾 `architecture_map.md` 对应层
3. 遇到疑问查 `pitfalls.md` 和 `best_practices.md`
4. 最后用 `smoke/run_all_examples.py` 验证全部通过
