# 学习路线 (Roadmap)

## 阶段一：基础入门

> 目标：理解 TaskIQ 核心概念，能跑通最小示例

| 顺序 | 文件 | 用途 |
|------|------|------|
| 1 | `examples/01_broker_and_config/01_taskiq_hello.py` | 最小可运行示例 |
| 2 | `examples/01_broker_and_config/02_result_backend.py` | 结果后端配置与结果获取 |
| 3 | `examples/01_broker_and_config/03_config_patterns.py` | 配置模式与环境变量 |

## 阶段二：任务定义与调用

> 目标：掌握任务定义、标签系统、调用方式

| 顺序 | 文件 | 用途 |
|------|------|------|
| 4 | `examples/02_task_definition/01_basic_task.py` | @broker.task 基本装饰 |
| 5 | `examples/02_task_definition/02_task_labels.py` | labels 标签系统 |
| 6 | `examples/03_task_invocation/01_kiq_and_kicker.py` | kiq() 与 kicker() 调用 |
| 7 | `examples/03_task_invocation/02_gather_parallel.py` | 并行任务与结果收集 |

## 阶段三：依赖注入（核心特色）

> 目标：掌握 TaskIQ 最具特色的依赖注入系统

| 顺序 | 文件 | 用途 |
|------|------|------|
| 8 | `examples/04_dependency_injection/01_depends_basics.py` | TaskiqDepends 基本用法 |
| 9 | `examples/04_dependency_injection/02_context_and_state.py` | Context 与 TaskiqState |
| 10 | `examples/04_dependency_injection/03_nested_depends.py` | 嵌套依赖与生命周期 |

## 阶段四：中间件与错误处理

> 目标：掌握中间件链和错误处理策略

| 顺序 | 文件 | 用途 |
|------|------|------|
| 11 | `examples/05_middlewares/01_builtin_middleware.py` | TaskiqMiddleware 6 个钩子 |
| 12 | `examples/05_middlewares/02_custom_middleware.py` | 自定义中间件 |
| 13 | `examples/05_middlewares/03_retry_middleware.py` | 指数退避重试中间件 |
| 14 | `examples/06_error_handling/01_reject_and_requeue.py` | reject/requeue 消息控制 |
| 15 | `examples/06_error_handling/02_smart_retry_with_backoff.py` | 智能重试策略 |

## 阶段五：高级特性

> 目标：掌握定时任务、生命周期、Broker 模式

| 顺序 | 文件 | 用途 |
|------|------|------|
| 16 | `examples/07_scheduling/01_redis_schedule_source.py` | Redis 调度源 |
| 17 | `examples/07_scheduling/02_cron_and_interval.py` | Cron 与间隔调度 |
| 18 | `examples/08_events_and_lifecycle/01_startup_shutdown.py` | 生命周期事件 |
| 19 | `examples/08_events_and_lifecycle/02_broker_events.py` | Broker 事件与 State |
| 20 | `examples/09_broker_patterns/01_pubsub_broker.py` | PubSub vs List 模式 |
| 21 | `examples/09_broker_patterns/02_multiple_queues.py` | 多队列路由 |

## 阶段六：FastAPI 集成

> 目标：在 Web 应用中集成 TaskIQ

| 顺序 | 文件 | 用途 |
|------|------|------|
| 22 | `examples/10_fastapi_integration/01_fastapi_taskiq.py` | FastAPI + TaskIQ 基础集成 |
| 23 | `examples/10_fastapi_integration/02_fastapi_depends_shared.py` | 共享依赖模式 |

## 阶段七：企业模板

> 目标：直接复用到生产项目

| 顺序 | 文件 | 用途 |
|------|------|------|
| 24 | `templates/taskiq_config.py` | 生产级配置对象 |
| 25 | `templates/taskiq_app.py` | Broker 工厂 + 单例管理 |
| 26 | `templates/error_handling.py` | 异常层级树 |
| 27 | `templates/task_base.py` | 任务装饰器工厂 |
| 28 | `templates/middleware_stack.py` | 生产级中间件栈 |
| 29 | `templates/fastapi_taskiq.py` | FastAPI 集成模板 |

## 建议学习方式

1. 按顺序逐文件运行：先启动 worker，再运行脚本，先看输出再读代码
2. 每章结束后回顾 `architecture_map.md` 对应层
3. 遇到疑问查 `pitfalls.md` 和 `best_practices.md`
4. 最后用 `smoke/run_all_examples.py` 验证全部通过
