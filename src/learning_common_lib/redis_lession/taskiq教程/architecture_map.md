# 架构全景图 (Architecture Map)

## TaskIQ 核心架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Producer (发布侧)                         │
│  FastAPI / Django / 脚本 / 定时调度器                              │
│                                                                 │
│  await task.kiq(args)  ──→  序列化为 JSON 消息                    │
│  task.kicker().kiq()        写入 Broker                          │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Broker (Redis)     │
                    │                      │
                    │  ListQueueBroker     │
                    │  ├─ LPUSH/BRPOP     │
                    │  └─ 竞争消费         │
                    │                      │
                    │  PubSubBroker        │
                    │  ├─ PUBLISH/SUB     │
                    │  └─ 广播模式         │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────▼──────┐ ┌──────▼───────┐ ┌──────▼───────┐
     │   Worker 1     │ │   Worker 2    │ │   Worker N    │
     │                │ │               │ │               │
     │  中间件链:      │ │  中间件链:     │ │  中间件链:     │
     │  pre_execute   │ │  pre_execute  │ │  pre_execute  │
     │  → 执行任务    │ │  → 执行任务   │ │  → 执行任务   │
     │  post_execute  │ │  post_execute │ │  post_execute │
     │                │ │               │ │               │
     │  依赖注入:      │ │  依赖注入:     │ │  依赖注入:     │
     │  TaskiqDepends │ │  TaskiqDepends│ │  TaskiqDepends│
     │  Context       │ │  Context      │ │  Context      │
     │  TaskiqState   │ │  TaskiqState  │ │  TaskiqState  │
     └────────┬──────┘ └──────┬───────┘ └──────┬───────┘
              │                │                │
              └────────────────┼────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Result Backend      │
                    │  (Redis DB 1)        │
                    │                      │
                    │  RedisAsyncResult    │
                    │  Backend             │
                    │  ├─ SET key value   │
                    │  ├─ result_ex_time  │
                    │  └─ TaskiqResult    │
                    └─────────────────────┘
```

## 消息生命周期

```
Producer                    Broker                     Worker
   │                          │                          │
   │  1. task.kiq(args)       │                          │
   │  ─────────────────────►  │                          │
   │  [pre_send 中间件]        │                          │
   │  [post_send 中间件]       │                          │
   │                          │  2. BRPOP 取出消息        │
   │                          │  ─────────────────────►  │
   │                          │                          │  3. [pre_execute 中间件]
   │                          │                          │  4. 解析依赖注入
   │                          │                          │  5. 执行任务函数
   │                          │                          │     async def → 事件循环
   │                          │                          │     sync def  → 默认 threadpool
   │                          │                          │  6. [post_execute 中间件]
   │                          │                          │  7. [post_save 中间件]
   │                          │                          │
   │                          │  8. 写入 Result Backend   │
   │                          │  ◄─────────────────────  │
   │                          │                          │
   │  9. wait_result()        │                          │
   │  ─────────────────────►  │                          │
   │  ◄─────────────────────  │                          │
   │  TaskiqResult            │                          │
```

## 对比 Celery 架构差异

| 维度 | Celery | TaskIQ |
|------|--------|--------|
| 异步模型 | 需要 celery-aio-pool 或 gevent | 原生 async/await |
| 依赖注入 | 无（需手动管理） | 内置 TaskiqDepends |
| 中间件 | Signals（松耦合） | Middleware 链（有序） |
| 任务调用 | delay() / apply_async() | kiq() / kicker().kiq() |
| 结果获取 | AsyncResult.get()（阻塞） | await handle.wait_result()（异步） |
| 并行等待 | group() + GroupResult | asyncio.gather() |
| 定时任务 | Celery Beat（独立进程） | TaskiqScheduler + ScheduleSource |
| Worker 执行模型 | prefork / gevent / custom | async def 走事件循环；sync def 默认进 threadpool |
| 任务元数据 | task.request | labels + Context |
| 消息确认 | acks_late 配置 | context.reject() / requeue() |

补充说明:
- TaskIQ 是 async-first，不等于“所有任务都天然异步并行”
- `async def` 里混入同步 IO 仍会阻塞事件循环
- CPU 密集型同步任务更适合 process pool，而不是无限堆线程

## 概念到文件映射表

| 概念 | 教程文件 | 模板文件 |
|------|----------|----------|
| Broker 创建 | `01_broker_and_config/01_taskiq_hello.py` | `templates/taskiq_config.py` |
| Result Backend | `01_broker_and_config/02_result_backend.py` | `templates/taskiq_config.py` |
| 配置模式 | `01_broker_and_config/03_config_patterns.py` | `templates/taskiq_config.py` |
| 任务定义 | `02_task_definition/01_basic_task.py` | `templates/task_base.py` |
| Labels 标签 | `02_task_definition/02_task_labels.py` | — |
| kiq/kicker | `03_task_invocation/01_kiq_and_kicker.py` | — |
| 并行执行 | `03_task_invocation/02_gather_parallel.py` | — |
| 依赖注入 | `04_dependency_injection/01_depends_basics.py` | — |
| Context/State | `04_dependency_injection/02_context_and_state.py` | — |
| 嵌套依赖 | `04_dependency_injection/03_nested_depends.py` | — |
| 中间件基础 | `05_middlewares/01_builtin_middleware.py` | `templates/middleware_stack.py` |
| 自定义中间件 | `05_middlewares/02_custom_middleware.py` | `templates/middleware_stack.py` |
| 重试中间件 | `05_middlewares/03_retry_middleware.py` | `templates/middleware_stack.py` |
| reject/requeue | `06_error_handling/01_reject_and_requeue.py` | `templates/error_handling.py` |
| 智能重试 | `06_error_handling/02_smart_retry_with_backoff.py` | `templates/error_handling.py` |
| 定时调度 | `07_scheduling/01_redis_schedule_source.py` | — |
| Cron/Interval | `07_scheduling/02_cron_and_interval.py` | — |
| 生命周期 | `08_events_and_lifecycle/01_startup_shutdown.py` | — |
| Broker 事件 | `08_events_and_lifecycle/02_broker_events.py` | — |
| PubSub/List | `09_broker_patterns/01_pubsub_broker.py` | — |
| 多队列 | `09_broker_patterns/02_multiple_queues.py` | — |
| FastAPI 集成 | `10_fastapi_integration/01_fastapi_taskiq.py` | `templates/fastapi_taskiq.py` |
| 共享依赖 | `10_fastapi_integration/02_fastapi_depends_shared.py` | `templates/fastapi_taskiq.py` |
| Broker 工厂 | — | `templates/taskiq_app.py` |
