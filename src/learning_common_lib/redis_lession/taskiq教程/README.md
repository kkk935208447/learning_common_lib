# TaskIQ 教程与企业级模板

## 删除重置 redis 内容
```python
import redis as redis_lib
def reset_tutorial_redis() -> None:
    """清空教程专用 Redis DB，避免示例之间互相污染。"""
    for db in (0, 1, 2, 3):
        client = redis_lib.Redis(
            host="localhost",
            port=6379,
            password="123456",
            db=db,
            socket_connect_timeout=3,
        )
        try:
            client.flushdb()
        finally:
            client.close()
reset_tutorial_redis()
```

## 查看和清理后台孤立的worker
```bash
# 查看 taskiq 所有 worker
ps -ef | grep taskiq
# 查看 celery 所有 worker
ps -ef | grep celery

# 删除 taskiq 所有 worker
pkill -9 -f taskiq
# 删除 celery 所有 worker
pkill -9 -f celery
```


## 定位

从零掌握 TaskIQ 异步任务队列框架，覆盖 Broker 配置、任务定义、调用、依赖注入、中间件、错误处理、定时任务、生命周期、RedisStreamBroker 深拆、Broker 模式、FastAPI 集成共 10+1 组渐进式示例，外加一套企业级可复用模板。

TaskIQ 是 Python 原生 async-first 的任务队列框架，相比 Celery 的优势：
- 原生 async/await（无需 celery-aio-pool 等 workaround）
- 内置依赖注入（类比 FastAPI 的 Depends）
- 中间件链（pre_send → post_send → pre_execute → post_execute → on_error → post_save）
- 更简洁的 API（kiq/kicker 替代 delay/apply_async）
- `async def` 任务走事件循环，`sync def` 默认走 threadpool，比在 Celery 里补 aio pool 更直接

## 适合谁

- 已掌握 Python 异步编程基础（asyncio / async-await）
- 需要在项目中引入 async-first 后台任务队列
- 希望快速搭建生产级 TaskIQ 骨架
- 从 Celery 迁移到 TaskIQ 的开发者

## Broker 对照速查

如果你是从 Celery 迁移过来的，最值得先建立的心智模型是：

- `Celery + Redis` 更像“Redis transport + visibility_timeout”
- `TaskIQ + RedisStreamBroker` 更像“Redis Stream + Consumer Group + ACK/reclaim”
- `Celery + RabbitMQ` 则是 Celery 更典型、更成熟的可靠 broker 主线

### Celery Redis broker vs TaskIQ RedisStreamBroker

| 维度 | Celery Redis broker | TaskIQ RedisStreamBroker |
|------|---------------------|--------------------------|
| 底层模型 | Redis transport，围绕 `visibility_timeout` 重投递 | Redis Stream + Consumer Group |
| ACK 语义 | 偏“可见性超时后再投递” | 显式 ACK，未 ACK 可 reclaim |
| 单 worker 多队列 | `celery worker -Q foo,bar` | 一个 broker 通过 `additional_streams` 监听多个 stream |
| producer 路由 | `task_routes` / `apply_async(queue=...)` | `queue_name` label |
| 对 Redis 原生模型的贴合度 | 较低，更偏 Celery transport | 高，直接就是 Stream 语义 |
| 更适合什么 | 已有 Celery + Redis 体系，继续沿用 | async-first + Redis-only + 更清晰的 ACK/reclaim 语义 |

重复执行风险补充：

- `Celery + Redis` 更容易因为长任务超过 `visibility_timeout` 而触发重复执行
- `TaskIQ + RedisStreamBroker` 也可能重复执行，但更像“未 ACK 消息被 reclaim 接管”，通常更可观测
- 两者都不应假设 exactly-once；任务逻辑依然要做幂等

### Celery RabbitMQ broker vs TaskIQ RedisStreamBroker

| 维度 | Celery RabbitMQ broker | TaskIQ RedisStreamBroker |
|------|-------------------------|--------------------------|
| 核心模型 | AMQP broker（exchange / queue / routing_key） | Redis Stream + Consumer Group |
| 确认机制 | RabbitMQ consumer ack / nack / requeue | Stream ACK / reclaim |
| 路由能力 | 强，Celery 原生强项 | 够用，依赖 `queue_name` + `additional_streams` |
| 多队列 worker | 原生支持，`-Q foo,bar` 很成熟 | 通过 broker 配置监听多个 stream |
| 优先级支持 | 更成熟，RabbitMQ 原生优先级更强 | 没有 RabbitMQ 那种 broker 原生优先级主模型 |
| 更适合什么 | Celery 正统生产主线、复杂路由和资源隔离 | Redis-only 栈、原生 async、想保留 Redis 流式消费语义 |

重复执行风险补充：

- `Celery + RabbitMQ` 也可能重复执行，但更常见触发点是 consumer/channel 失联，而不是单纯任务过长
- `TaskIQ + RedisStreamBroker` 的重复执行通常对应 idle timeout / pending reclaim
- 如果你最担心“长短任务参差不齐导致天然重复执行”，RabbitMQ 一般比 Celery Redis 更稳

补充理解：

- 如果你只是想把 Celery + Redis 迁到 TaskIQ，不要直接把两者当成同一种 Redis broker
- 如果你想保留 Redis，但同时得到更接近可靠消息流的语义，优先评估 `RedisStreamBroker`
- 如果你继续用 Celery 且非常看重 broker 能力，RabbitMQ 仍然是更典型的主线选择

## 三层职责

- `examples/`
  每个文件都是独立教学案例，优先讲清一个概念，强调运行中间态和前后对照。
- `templates/`
  企业级可复用骨架，目标是高并发、稳定性和较低认知负担，不追求“把所有概念塞在一个模块里”。
- `smoke/`
  自动化验收层，统一验证 `examples/` 与 `templates/` 是否都还能独立运行。

## 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 运行环境 |
| taskiq | 0.12+ | 任务队列框架 |
| taskiq-redis | 1.1+ | Redis broker + result backend |
| taskiq-dependencies | 1.5+ | 依赖注入 |
| redis | 5.0+ | redis-py（smoke test 清理用） |
| fastapi | 0.100+ | 第 10 章集成 |
| uvicorn | 0.20+ | 第 10 章集成 |

## 环境准备

```bash
# 1. 确保 Redis 已启动（带密码 123456）
docker exec <redis容器名> redis-cli -a 123456 ping  # 应返回 PONG

# 2. 安装依赖（已在 pyproject.toml 中声明）
uv sync
```
## 终端查看后台开启的 taskiq 进程
```bash
ps -ef | grep taskiq
# 删除所有的 taskiq 进程
pkill -9 -f taskiq
```

## 目录结构

```
taskiq教程/
├── README.md                ← 本文件
├── architecture_map.md      ← 架构全景图
├── best_practices.md        ← 最佳实践
├── pitfalls.md              ← 常见陷阱
├── roadmap.md               ← 学习路线
├── smoke/
│   └── run_all_examples.py  ← 一键验证 examples + templates
├── examples/
│   ├── 01_broker_and_config/   ← Broker 实例与配置
│   ├── 02_task_definition/     ← 任务定义
│   ├── 03_task_invocation/     ← 任务调用
│   ├── 04_dependency_injection/ ← 依赖注入（TaskIQ 核心特色）
│   ├── 05_middlewares/         ← 中间件
│   ├── 06_error_handling/      ← 错误处理
│   ├── 07_scheduling/          ← 定时任务
│   ├── 08_events_and_lifecycle/ ← 事件与生命周期
│   ├── 08_redis_stream_broker/ ← RedisStreamBroker 深度拆解（插入 09 章之前）
│   ├── 09_broker_patterns/     ← Broker 模式
│   └── 10_fastapi_integration/ ← FastAPI 集成
├── templates/
│   ├── __init__.py          ← 公开 API 导出
│   ├── README.md            ← 模板使用指南
│   ├── taskiq_config.py     ← 生产级配置
│   ├── taskiq_app.py        ← Broker 工厂 + 单例管理
│   ├── error_handling.py    ← 异常层级树
│   ├── task_base.py         ← 任务装饰器工厂 + sync/async 安全包装
│   ├── middleware_stack.py  ← 生产级中间件栈
│   └── fastapi_taskiq.py    ← FastAPI 集成
└── 简单的测试/              ← 早期测试代码（保留）
```

## 快速开始

```bash
cd src/learning_common_lib/redis_lession/taskiq教程

# 如果之前运行过其他示例，建议先清理 Redis：
redis-cli -a 123456 -n 0 FLUSHDB && redis-cli -a 123456 -n 1 FLUSHDB

# 终端 1: 启动 Worker
taskiq worker examples.01_broker_and_config.01_taskiq_hello:broker

# 终端 2: 运行示例
uv run python examples/01_broker_and_config/01_taskiq_hello.py

# 一键验证 examples + templates（自动启动/停止 worker）
uv run python smoke/run_all_examples.py

# 单独运行任意模板的 _demo()
uv run python -m templates.task_base
```

## Worker 启动方式

每个示例需要两个终端运行：

| 终端 | 命令 | 说明 |
|------|------|------|
| 终端 1 | `taskiq worker examples.XX_topic.YY_file:broker` | 启动 Worker |
| 终端 2 | `uv run python examples/XX_topic/YY_file.py` | 运行客户端脚本 |

参数说明：
- `examples.XX_topic.YY_file:broker`：指定 broker 对象所在的模块路径
- `async def` 任务走事件循环；`sync def` 默认走 threadpool
- CPU 密集型任务建议考虑 `--use-process-pool` 与 `--max-process-pool-processes`
- 个别示例会使用非默认入口，如 `:list_broker`、`:default_broker`

## Smoke 验证策略

- `examples/` 默认运行 `main()`；需要 worker 的案例由 smoke 自动启动对应 worker
- `templates/` 默认运行各模块 `_demo()`，不启动 worker
- smoke 会为需要 worker 的示例注入独立 `queue_name`，避免和你手工启动的教程 worker 抢同一个队列
- 单个 worker 完全可以在同一个队列里处理多个不同 `task_name`
- 多个 worker 也可以共享同一个队列，但前提是它们本来就是同一组消费者：注册的任务集合一致，或者至少都认识这批任务
- TaskIQ 的 `ListQueueBroker` 是先竞争消费、再按 `task_name` 找函数；真正危险的是“任务注册集合不一致的 worker”共享同一个队列
- 单 broker 示例统一支持 `TASKIQ_QUEUE_NAME`；多 broker 示例支持 `TASKIQ_QUEUE_NAME_<BROKER_NAME>`
- 每个文件运行前后都会清理 Redis DB 0/1/2/3，尽量减少示例之间的状态污染

这个问题不是 smoke 独有问题，而是 TaskIQ + Redis ListQueueBroker 的工作方式决定的：

- Redis 先把消息从队列里弹出
- worker 再在本地按 `task_name` 查任务注册表
- 如果抢到消息的 worker 没注册这个任务，消息会被直接丢弃，而不是自动回队列
- 所以“同一组同构 worker 共享一个队列”是正常模式；“不同服务或不同示例共享一个队列”才是风险点

## 章节概览

| 章 | 主题 | 内容 |
|----|------|------|
| 01 | Broker 与配置 | ListQueueBroker、RedisAsyncResultBackend、环境变量覆盖 |
| 02 | 任务定义 | @broker.task、task_name、labels 标签系统 |
| 03 | 任务调用 | kiq() 快捷调用、kicker() 高级调用、asyncio.gather 并行 |
| 04 | 依赖注入 | TaskiqDepends、Context、TaskiqState、嵌套依赖 |
| 05 | 中间件 | TaskiqMiddleware 6 个钩子、自定义中间件、重试中间件 |
| 06 | 错误处理 | reject/requeue、智能重试 + 指数退避 |
| 07 | 定时任务 | RedisScheduleSource、cron 表达式、间隔调度 |
| 08 | 事件与生命周期 | WORKER_STARTUP/SHUTDOWN、broker.on_event、TaskiqState |
| 08+ | RedisStreamBroker 深拆 | Stream 基础、ACK、reclaim、单 broker 动态 `queue_name` 路由 |
| 09 | Broker 模式 | PubSubBroker vs ListQueueBroker、多 broker 多队列路由、单 broker 动态 stream/list 路由总结 |
| 10 | FastAPI 集成 | lifespan 管理、共享依赖、统一响应格式 |

插入小章节：

- `examples/08_redis_stream_broker/README.md`
  解释 `RedisStreamBroker`、`ListQueueBroker`、动态 `queue_name` 路由、Consumer Group / ACK / `XAUTOCLAIM` 的差异与生产取舍。

## Redis 连接约定

```
broker:         redis://default:123456@localhost:6379/0
result_backend: redis://default:123456@localhost:6379/1
```

分库避免 key 冲突，带密码认证。
