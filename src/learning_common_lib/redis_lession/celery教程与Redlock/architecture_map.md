# 架构全景图 (Architecture Map)

## Celery 核心架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Producer (发布侧)                         │
│  FastAPI / Django / 脚本 / 定时调度器                              │
│                                                                 │
│  task.delay(args)  ──→  序列化为 JSON 消息                        │
│  task.apply_async()     写入 Broker 队列                          │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Broker (消息中间件)                           │
│                                                                 │
│  Redis db=0  /  RabbitMQ  /  Amazon SQS                         │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ default  │  │  email   │  │  report  │  │ priority │       │
│  │  queue   │  │  queue   │  │  queue   │  │  queue   │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Worker (消费侧)                              │
│                                                                 │
│  celery -A app worker -Q default,email --concurrency=4          │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Prefork Pool (默认)                                     │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐          │   │
│  │  │ Worker │ │ Worker │ │ Worker │ │ Worker │          │   │
│  │  │  子进程 │ │  子进程 │ │  子进程 │ │  子进程 │          │   │
│  │  └────────┘ └────────┘ └────────┘ └────────┘          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  任务执行 → 结果写入 Result Backend                               │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Result Backend (结果存储)                       │
│                                                                 │
│  Redis db=1  /  数据库  /  Memcached                             │
│                                                                 │
│  key: celery-task-meta-{task_id}                                │
│  value: {"status": "SUCCESS", "result": ..., "traceback": ...}  │
│  TTL: result_expires (默认 86400s)                               │
└─────────────────────────────────────────────────────────────────┘
```

## 任务状态机

```
                    ┌──────────┐
                    │ PENDING  │  ← 任务已发布，尚未被 worker 接收
                    └────┬─────┘
                         │  worker 接收
                         ▼
                    ┌──────────┐
                    │ STARTED  │  ← worker 开始执行（需 task_track_started=True）
                    └────┬─────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ SUCCESS  │ │ FAILURE  │ │ REVOKED  │
        └──────────┘ └────┬─────┘ └──────────┘
                          │
                          ▼  self.retry()
                    ┌──────────┐
                    │  RETRY   │ ──→ 重新进入 PENDING
                    └──────────┘
```

## Celery Beat 定时调度

```
┌──────────────┐     beat_schedule      ┌──────────────┐
│ Celery Beat  │ ──────────────────────→│   Broker     │
│  (调度进程)   │  按 crontab/timedelta  │  (消息队列)   │
│              │  定时发布任务消息        │              │
└──────────────┘                        └──────┬───────┘
                                               │
                                               ▼
                                        ┌──────────────┐
                                        │   Worker     │
                                        └──────────────┘
```

## 工作流编排

```
chain:    task_A  →  task_B  →  task_C     (串行，结果传递)

group:    ┌─ task_A ─┐
          ├─ task_B ─┤                     (并行，各自独立)
          └─ task_C ─┘

chord:    ┌─ task_A ─┐
          ├─ task_B ─┤ → callback(results) (并行 + 汇总回调)
          └─ task_C ─┘

chunks:   [item1, item2, ..., itemN]
          → chunk_1(items[:k])             (分批处理)
          → chunk_2(items[k:2k])
          → ...
```

## Redlock 分布式锁

```
┌──────────┐                        ┌──────────┐
│ Worker A │ ── SET lock NX EX ──→ │  Redis   │ ── 获取成功 ✅
└──────────┘                        │          │
                                    │  key:    │
┌──────────┐                        │  lock:   │
│ Worker B │ ── SET lock NX EX ──→ │  order:  │ ── 获取失败 ❌
└──────────┘                        │  123     │    (key 已存在)
                                    └──────────┘

流程:
1. 尝试 SET key value NX EX timeout
2. 成功 → 执行业务逻辑 → DEL key 释放锁
3. 失败 → 抛出 LockAcquireError 或等待重试

redis-py Lock 内部实现:
- 使用 Lua 脚本保证原子性
- 支持自动续期（extend）
- 释放时校验 owner token，防止误删他人锁
```

## Worker 生命周期

```
启动阶段:
  1. 加载 Celery App 和配置
  2. 连接 Broker (Redis db=0)
  3. 连接 Result Backend (Redis db=1)
  4. 注册所有任务
  5. 启动 Worker Pool (prefork/solo/gevent/eventlet)
  6. 开始消费队列消息

运行阶段:
  Broker 队列 → 取消息 → 反序列化 → 执行任务函数 → 序列化结果 → 写入 Backend

关闭阶段:
  1. 停止接收新消息
  2. 等待当前任务完成 (warm shutdown)
  3. 关闭连接池
```

## Worker Pool 模型对比

| Pool | 并发模型 | 适用场景 | 启动参数 |
|------|---------|---------|---------|
| prefork | 多进程 | CPU 密集型（默认） | `-P prefork -c 4` |
| solo | 单线程 | 教程演示、调试 | `-P solo` |
| gevent | 协程 | IO 密集型 | `-P gevent -c 100` |
| eventlet | 协程 | IO 密集型 | `-P eventlet -c 100` |

## 消息流转详细图

```
Producer                    Broker (Redis)              Worker
   │                            │                         │
   │  1. json.dumps(args)       │                         │
   │  2. LPUSH queue msg ──────→│                         │
   │                            │  3. BRPOP queue ───────→│
   │                            │                         │  4. json.loads(msg)
   │                            │                         │  5. task_func(*args)
   │                            │                         │  6. json.dumps(result)
   │                            │  7. SET task-meta ←─────│
   │  8. GET task-meta ────────→│                         │
   │  ←── result ───────────────│                         │
```

## 概念到文件映射

| 架构层 | 概念 | 教程文件 | 模板文件 |
|--------|------|---------|---------|
| 配置层 | App 创建、参数 | 01 章 | `celery_config.py`, `celery_app.py` |
| 任务层 | 定义、序列化 | 02 章 | `task_base.py` |
| 发布层 | 调用、签名 | 03 章 | `celery_app.py` (async_delay) |
| 结果层 | 状态、过期 | 04 章 | `celery_config.py` (result_expires) |
| 容错层 | 重试、异常 | 05 章 | `error_handling.py`, `task_base.py` |
| 路由层 | 队列、优先级 | 06 章 | `celery_config.py` (task_routes) |
| 调度层 | Beat、动态 | 07 章 | — |
| 编排层 | chain/group/chord | 08 章 | — |
| 监控层 | 信号、Flower | 09 章 | — |
| 集成层 | FastAPI、Redlock | 10 章 | `fastapi_celery.py`, `redlock.py` |
