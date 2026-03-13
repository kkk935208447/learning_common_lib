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

## 阶段二：结果与容错（第 4-5 章）

> 目标：掌握结果获取与错误恢复策略

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 8 | `examples/04_result_backend/01_async_result.py` | AsyncResult 状态机、get/forget | 知道任务执行到哪了 |
| 9 | `examples/04_result_backend/02_result_expiry.py` | result_expires 配置 | 防止 Redis 内存爆炸 |
| 10 | `examples/05_error_handling/01_retry_basics.py` | self.retry/max_retries/countdown | 任务失败不可怕，重试才是关键 |
| 11 | `examples/05_error_handling/02_autoretry.py` | autoretry_for/retry_backoff | 自动重试更省心 |

> 每个示例需要两个终端：一个启动 worker，一个运行脚本。详见各文件顶部 docstring。

## 阶段三：生产级特性（第 6-8 章）

> 目标：多队列路由、定时调度、工作流编排

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 12 | `examples/06_routing_and_queues/01_task_queues.py` | 多队列、task_routes | 不同任务走不同通道 |
| 13 | `examples/06_routing_and_queues/02_priority.py` | 优先级队列 | 紧急任务插队 |
| 14 | `examples/07_periodic_tasks/01_celery_beat.py` | beat_schedule/crontab | 定时任务调度 |
| 15 | `examples/07_periodic_tasks/02_dynamic_schedule.py` | 运行时增删定时任务 | 动态调度需求 |
| 16 | `examples/08_workflows/01_chain_and_group.py` | chain/group/错误传播 | 任务编排基础 |
| 17 | `examples/08_workflows/02_chord_and_chunks.py` | chord/chunks | 并行计算 + 汇总 |

> 每个示例需要两个终端：一个启动 worker，一个运行脚本。详见各文件顶部 docstring。

## 阶段四：监控与集成（第 9-10 章）

> 目标：生产监控、FastAPI 集成、分布式锁

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 18 | `examples/09_signals_and_monitoring/01_task_signals.py` | task_prerun/postrun/failure 信号 | 任务生命周期钩子 |
| 19 | `examples/09_signals_and_monitoring/02_flower_and_events.py` | Flower 监控 + 自定义事件 | 生产可观测性 |
| 20 | `examples/10_fastapi_integration/01_fastapi_celery.py` | FastAPI + Celery 触发/轮询 | Web 框架集成 |
| 21 | `examples/10_fastapi_integration/02_distributed_lock.py` | 单 Redis 分布式锁基础篇 | 先理解锁原理和竞争 |
| 22 | `examples/10_fastapi_integration/03_watchdog_lock_with_celery.py` | python-redis-lock 企业篇 | 理解长任务自动续期 |

> 每个示例需要两个终端：一个启动 worker，一个运行脚本。详见各文件顶部 docstring。

## 阶段五：企业模板

> 目标：直接复用到生产项目

| 顺序 | 文件 | 用途 |
|------|------|------|
| 23 | `templates/celery_config.py` | 生产级配置对象 |
| 24 | `templates/celery_app.py` | App 工厂 + 异步包装 |
| 25 | `templates/error_handling.py` | 异常层级树 |
| 26 | `templates/task_base.py` | 基础任务类 |
| 27 | `templates/distributed_lock.py` | 企业级 python-redis-lock 分布式锁 |
| 28 | `templates/fastapi_celery.py` | FastAPI 集成 |

## 建议学习方式

1. 按顺序逐文件运行：先启动 worker，再运行脚本，先看输出再读代码
2. 每章结束后回顾 `architecture_map.md` 对应层
3. 遇到疑问查 `pitfalls.md` 和 `best_practices.md`
4. 最后用 `smoke/run_all_examples.py` 验证全部通过
