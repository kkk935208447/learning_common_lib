# Celery 教程与 Redis 分布式锁

## 删除重置 redis 内容
```python
import redis as redis_lib
def reset_tutorial_redis() -> None:
    """清空教程专用 Redis DB，避免示例之间互相污染。"""
    for db in (0, 1, 2, 3, 4):
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

从零掌握 Celery 分布式任务队列 + Redis 分布式锁，覆盖配置、任务定义、调用、async worker、结果、重试、路由、定时、工作流、监控、FastAPI 集成共 11 章渐进式示例，外加一套企业级可复用模板。

说明：
- 当前目录名仍然保留历史名称 `celery教程与Redlock`
- 教程主线讨论的是“服务分布式部署，但锁底座是单 Redis”的分布式锁
- 不把多 Redis 节点的 Redlock 算法作为本教程主线

## 适合谁

- 已掌握 Python 异步编程基础（asyncio / async-await）
- 需要在项目中引入后台任务队列或分布式锁
- 希望快速搭建生产级 Celery 骨架

## Broker 对照速查

在 Redis / RabbitMQ / TaskIQ 之间切换时，最容易混淆的是：

- `Celery + Redis` 更像“Redis transport + visibility_timeout”
- `TaskIQ + RedisStreamBroker` 更像“Redis Stream + Consumer Group + ACK/reclaim”
- `Celery + RabbitMQ` 则是 Celery 更典型、也更成熟的可靠 broker 主线

### Celery Redis broker vs TaskIQ RedisStreamBroker

| 维度 | Celery Redis broker | TaskIQ RedisStreamBroker |
|------|---------------------|--------------------------|
| 底层模型 | Redis transport，围绕 `visibility_timeout` 重投递 | Redis Stream + Consumer Group |
| ACK 语义 | 偏“可见性超时后再投递” | 显式 ACK，未 ACK 可 reclaim |
| 多队列 worker | `celery worker -Q foo,bar` | 一个 broker 通过 `additional_streams` 监听多个 stream |
| producer 路由 | `task_routes` / `apply_async(queue=...)` | `queue_name` label |
| 对 Redis 原生模型的贴合度 | 较低，更偏 Celery transport | 高，直接就是 Stream 语义 |
| 更适合什么 | 已有 Celery + Redis 体系，继续沿用 | async-first + Redis-only + 更清晰的 ACK/reclaim 语义 |

重复执行风险补充：

- `Celery + Redis` 更容易因为长任务超过 `visibility_timeout` 而触发重复执行
- `TaskIQ + RedisStreamBroker` 也可能重复执行，但更像“未 ACK 消息被 reclaim 接管”，通常比 Celery Redis 更可观测
- 两者都应按 at-least-once 语义设计任务幂等

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
- 从“长任务天然触发重复执行”的角度看，RabbitMQ 通常比 Celery Redis 更稳

补充理解：

- 如果你继续用 Celery，但追求更成熟的 broker 语义，通常优先考虑 RabbitMQ
- 如果你想在 Redis 里拿到更“原生消息流”的模型，TaskIQ 的 `RedisStreamBroker` 更贴近这个方向
- 本教程主线仍然以 Celery + Redis 为例，但你可以把上面两张表当成选型背景板

## 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 运行环境 |
| celery[redis] | 5.3+ | 任务队列 + Redis broker/backend |
| celery-aio-pool | 0.1.0rc8+ | 第 4 章 async worker / async task |
| gevent | 25.5+ | 第 4 章官方 greenlet 中间态 |
| redis | 5.0+ | redis-py（内置 Lock 支持） |
| python-redis-lock | 4.0+ | 同步 Redis 锁兼容模板（可选） |
| flower | 2.0+ | 第 10 章监控 |
| fastapi | 0.100+ | 第 11 章集成 |
| uvicorn | 0.20+ | 第 11 章集成 |

## 环境准备

```bash
# 1. 确保 Redis 已启动（带密码 123456）
# Docker 方式验证:
docker exec <redis容器名> redis-cli -a 123456 ping  # 应返回 PONG
# 或 Python 方式验证:
python -c "import redis; print(redis.Redis(host='localhost', port=6379, password='123456').ping())"

# 2. 安装依赖
uv add "celery[redis]" "celery-aio-pool>=0.1.0rc8" "gevent>=25.5.1" "redis>=5.0" flower fastapi uvicorn

# 如果你还需要同步 Redis / python-redis-lock 兼容模板，再额外安装
uv add "python-redis-lock>=4.0.0"
```


## 目录结构

```
celery教程与Redlock/
├── README.md                ← 本文件
├── architecture_map.md      ← 架构全景图
├── best_practices.md        ← 最佳实践
├── pitfalls.md              ← 常见陷阱
├── distributed_lock_guide.md ← 分布式锁原理与队列关系
├── smoke/
│   └── run_all_examples.py  ← 一键验证所有示例
├── examples/
│   ├── 01_app_and_config/   ← Celery 实例与配置（含 acks_late 运行时示例）
│   ├── 02_task_definition/  ← 任务定义
│   ├── 03_task_invocation/  ← 任务调用
│   ├── 04_async_worker_tasks/ ← prefork → gevent → custom aio pool
│   ├── 05_result_backend/   ← 结果后端
│   ├── 06_error_handling/   ← 错误与重试
│   ├── 07_routing_and_queues/ ← 路由与队列
│   ├── 08_periodic_tasks/   ← 定时任务
│   ├── 09_workflows/        ← 工作流编排
│   ├── 10_signals_and_monitoring/ ← 信号与监控
│   └── 11_fastapi_integration/   ← FastAPI + Redis 分布式锁（固定 TTL → 最小看门狗 → 企业篇）
└── templates/
    ├── __init__.py          ← 公开 API 导出
    ├── celery_config.py     ← 生产级配置
    ├── celery_app.py        ← async-first App 工厂 + producer 侧异步包装
    ├── error_handling.py    ← 异常层级树
    ├── task_base.py         ← async-first 任务基类
    ├── distributed_lock.py  ← 同步 Redis / python-redis-lock 兼容模板
    ├── distributed_lock_aio.py ← 纯异步 Redis 看门狗锁模板
    └── fastapi_celery.py    ← FastAPI 集成
```

## 快速开始

```bash
cd src/learning_common_lib/redis_lession/celery教程与Redlock

# 如果之前运行过其他示例，建议先清理 Redis（注意：该命令需要环境中已安装 redis-cli 工具），如果没有安装 redis-cli 工具，也可以使用上文 Python 代码清理 Redis 内容
redis-cli -a 123456 -n 0 FLUSHDB && redis-cli -a 123456 -n 1 FLUSHDB

# 终端 1: 启动 Worker。注意：如果没有启动 Worker 时，率先启动了客户端脚本，会导致任务积压到redis队列中，可能会对后面启动的 Worker 的任务进行污染。如何清理这些任务？使用命令 purge -f 例如：uv run celery -A examples.06_error_handling.01_retry_basics purge -f
celery -A examples.01_app_and_config.01_celery_hello worker -l info -P solo

# 终端 2: 运行示例
uv run python examples/01_app_and_config/01_celery_hello.py

# 一键验证全部示例（自动启动/停止 worker）
uv run python smoke/run_all_examples.py
```

## Worker 启动方式

每个示例需要两个终端运行：

| 终端 | 命令 | 说明 |
|------|------|------|
| 终端 1 | `celery -A examples.XX_topic.YY_file worker -l info -P <pool>` | 启动 Worker |
| 终端 2 | `uv run python examples/XX_topic/YY_file.py` | 运行客户端脚本 |

参数说明：
- `-A`: 指定 Celery app 所在模块
- `-l info`: 日志级别
- `-P prefork|solo|gevent|custom`: 指定 worker 并发模型
- `-c N`: 设置并发数，greenlet/aio pool 示例通常需要显式配置
- `-Q queue1,queue2`: 指定消费的队列（第 7 章路由示例需要）

默认队列提醒：

- Celery 默认队列通常是 `celery`
- 单个 worker 完全可以在同一个队列里处理多个不同任务；多个 worker 共享同一个队列做横向扩容也是正常模式
- 真正危险的是多个 worker 监听同一个默认队列，但它们导入的任务集合或 `task_routes` 配置不一致
- 这时常见表现不是“完全没问题”，而是 `Received unregistered task`、任务积压、错误路由、结果超时
- 生产环境不要长期依赖默认 `celery` 队列；尽量显式设置 `task_default_queue`，并配合 `task_routes` 和 worker `-Q` 做职责隔离

第 4 章 async worker 示例额外需要：
- `-P prefork`: 作为传统同步 worker 基线
- `-P gevent`: 官方 greenlet 并发池
- `CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool'`
- `-P custom`: 告诉 Celery 使用自定义 worker pool
- 建议把三类任务拆到独立队列，例如 `prefork_jobs / greenlet_jobs / aio_jobs`

## Async Worker 先导说明

第 4 章会明确对比三层执行模型：

- `prefork`: 默认基线，worker 执行 sync def task
- `gevent`: 官方 greenlet 中间态，仍是 sync def task，但适合 cooperative IO
- `custom aio pool`: 真正把 worker 执行层接到 `asyncio`

在进入第 4 章之前，所有示例都主要建立在 Celery 经典同步执行模型上：

- `asyncio.to_thread(task.delay, ...)` 只是在 async producer 中安全调用 Celery 同步 API
- 它不会自动把 worker 侧变成原生 async 执行
- 如果你想在 worker 中真正运行 `async def task`，需要 `custom aio pool`

因此本教程把 async worker 单独拆成第 4 章，先讲清 `prefork → gevent → custom aio pool` 的边界，再继续学习结果后端、重试、队列、FastAPI 等后续章节。

再补一条很容易混淆的边界：

- 第 11 章里的 `send_task()`、`AsyncResult` 仍然不是“底层 fully async 客户端”
- 它们仍然分别建立在 Celery 同步客户端、同步结果客户端之上
- 但锁模板现在拆成两条线：
  - `templates/distributed_lock_aio.py` 是原生 `redis.asyncio` 实现
  - `templates/distributed_lock.py` 是同步 Redis / `python-redis-lock` 兼容实现
- 教程里使用 `asyncio.to_thread(...)` 的目的，是让 async 调用侧不阻塞事件循环，而不是声称所有底层实现都已经完成 async 化

## 命名与启动的生产约定

教程示例为了方便演示，很多文件把 `app` 和任务写在同一个模块里，并直接用
`celery -A examples.xx.yy worker` 启动。生产环境建议改成更稳定的结构：

```python
# myproj/celery_app.py
from celery import Celery

app = Celery("myproj")
app.config_from_object("myproj.settings.celery")
app.autodiscover_tasks(["myproj"])
```

```bash
# 更常见的生产启动方式
celery -A myproj.celery_app:app worker -l info

# 如果 myproj/__init__.py 里导出了 app，也可以简写
celery -A myproj worker -l info
```

命名建议：
- `Celery("myproj")` 的第一个参数用稳定的项目包名，不要用 `add_test`、`worker` 这类教学或临时名字
- 任务优先使用自动生成的绝对模块路径名，例如 `myproj.orders.tasks.process_order`
- 只有在“跨服务固定契约”或“重构期间要保持旧名字兼容”时，才显式写 `@app.task(name="myproj.orders.process_order")`
- 不要在生产里依赖“直接运行 task 文件”这种模式；统一通过包模块导入和 `celery -A pkg.module:app` 启动

这样做的好处：
- worker / client / beat / Flower 都引用同一个可导入的 app 入口
- 任务名天然稳定，降低 `NotRegistered` 和路由漂移风险
- 部署命令与官方文档、进程管理器、容器启动脚本更一致

## 学习路线概览

| 章 | 主题 | 核心知识点 |
|----|------|-----------|
| 01 | App 与配置 | Celery 实例创建、broker/backend 角色、配置方式对比、`acks_late` 与 `broker_transport_options` 区别 |
| 02 | 任务定义 | @app.task 参数、bind=True、序列化约束 |
| 03 | 任务调用 | delay/apply_async、Signature、countdown/ETA |
| 04 | Async Worker | `prefork → gevent → custom aio pool`、`asyncio.run()`、mixed deployment |
| 05 | 结果后端 | `custom aio pool + async task` 下的 AsyncResult 状态机、result_expires |
| 06 | 错误与重试 | `custom aio pool + async task` 下的 self.retry() / opt-in `@async_autoretry(...)` 装饰器 / 指数退避 |
| 07 | 路由与队列 | 多队列分流、task_routes、优先级队列 |
| 08 | 定时任务 | Celery Beat、crontab、动态调度 |
| 09 | 工作流 | chain/group/chord/chunks |
| 10 | 信号与监控 | task signals、Flower、自定义事件 |
| 11 | FastAPI 集成 | async-first worker + FastAPI 触发任务/轮询状态/Redis 分布式锁时间轴 |

第 11 章中的锁示例分为三层：
- `02_distributed_lock.py`：基础篇，用上下文管理器演示“短任务固定 TTL 正常”与“长任务固定 TTL 失锁”，并打印客户端侧 TTL 时间轴
- `03_python_redis_lock_watchdog_minimal.py`：最小看门狗篇，不引入 Celery，只看 `python-redis-lock` 的 `auto_renewal` 如何续期
- `03_python_redis_lock_watchdog_minimal2.py`：纯异步看门狗篇，不引入 Celery，只看 `redis.asyncio` + asyncio 看门狗如何续期
- `04_watchdog_lock_with_celery.py`：企业篇，把纯异步看门狗放进 `custom aio pool + async task` 的 worker 场景

第 11 章默认先坚持上下文管理器视角：

- 先把获取锁、TTL 倒计时、续期、释放这些中间态看明白
- 再接受模板里保留 `@with_lock` 这类语法糖，但不把它作为第一阅读入口

## Redis 连接约定

```
broker:  redis://:123456@localhost:6379/0
backend: redis://:123456@localhost:6379/1
lock:    redis://:123456@localhost:6379/2
```

分库避免 key 冲突，带密码认证。
