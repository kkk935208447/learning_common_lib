# Celery 教程与 Redis 分布式锁

## 定位

从零掌握 Celery 分布式任务队列 + Redis 分布式锁，覆盖配置、任务定义、调用、结果、重试、路由、定时、工作流、监控、FastAPI 集成共 10 章渐进式示例，外加一套企业级可复用模板。

说明：
- 当前目录名仍然保留历史名称 `celery教程与Redlock`
- 教程主线讨论的是“服务分布式部署，但锁底座是单 Redis”的分布式锁
- 不把多 Redis 节点的 Redlock 算法作为本教程主线

## 适合谁

- 已掌握 Python 异步编程基础（asyncio / async-await）
- 需要在项目中引入后台任务队列或分布式锁
- 希望快速搭建生产级 Celery 骨架

## 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 运行环境 |
| celery[redis] | 5.3+ | 任务队列 + Redis broker/backend |
| redis | 5.0+ | redis-py（内置 Lock 支持） |
| python-redis-lock | 4.0+ | 企业级分布式锁自动续期 |
| flower | 2.0+ | 第 9 章监控 |
| fastapi | 0.100+ | 第 10 章集成 |
| uvicorn | 0.20+ | 第 10 章集成 |

## 环境准备

```bash
# 1. 确保 Redis 已启动（带密码 123456）
# Docker 方式验证:
docker exec <redis容器名> redis-cli -a 123456 ping  # 应返回 PONG
# 或 Python 方式验证:
python -c "import redis; print(redis.Redis(host='localhost', port=6379, password='123456').ping())"

# 2. 安装依赖
uv add "celery[redis]" "redis>=5.0" "python-redis-lock>=4.0.0" flower fastapi uvicorn
```

## 终端查看后台开启的 celery 进程
```bash
ps -ef | grep celery
# ps aux | grep celery
# 删除所有的 celery,  -9 表示强制删除
pkill -9 -f celery 
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
│   ├── 04_result_backend/   ← 结果后端
│   ├── 05_error_handling/   ← 错误与重试
│   ├── 06_routing_and_queues/ ← 路由与队列
│   ├── 07_periodic_tasks/   ← 定时任务
│   ├── 08_workflows/        ← 工作流编排
│   ├── 09_signals_and_monitoring/ ← 信号与监控
│   └── 10_fastapi_integration/   ← FastAPI + Redis 分布式锁（基础篇 + 企业篇）
└── templates/
    ├── __init__.py          ← 公开 API 导出
    ├── celery_config.py     ← 生产级配置
    ├── celery_app.py        ← App 工厂 + 异步包装
    ├── error_handling.py    ← 异常层级树
    ├── task_base.py         ← 基础任务类
    ├── distributed_lock.py  ← 企业级 python-redis-lock 分布式锁模板
    ├── redlock.py           ← 历史兼容别名
    └── fastapi_celery.py    ← FastAPI 集成
```

## 快速开始

```bash
cd src/learning_common_lib/redis_lession/celery教程与Redlock

# 如果之前运行过其他示例，建议先清理 Redis：
redis-cli -a 123456 -n 0 FLUSHDB && redis-cli -a 123456 -n 1 FLUSHDB

# 终端 1: 启动 Worker
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
| 终端 1 | `celery -A examples.XX_topic.YY_file worker -l info -P solo` | 启动 Worker |
| 终端 2 | `uv run python examples/XX_topic/YY_file.py` | 运行客户端脚本 |

参数说明：
- `-A`: 指定 Celery app 所在模块
- `-l info`: 日志级别
- `-P solo`: 单线程池，适合教程演示
- `-Q queue1,queue2`: 指定消费的队列（第 6 章路由示例需要）

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
| 04 | 结果后端 | AsyncResult 状态机、result_expires |
| 05 | 错误与重试 | self.retry()、autoretry_for、指数退避 |
| 06 | 路由与队列 | 多队列分流、task_routes、优先级队列 |
| 07 | 定时任务 | Celery Beat、crontab、动态调度 |
| 08 | 工作流 | chain/group/chord/chunks |
| 09 | 信号与监控 | task signals、Flower、自定义事件 |
| 10 | FastAPI 集成 | 触发任务/轮询状态/Redis 分布式锁 |

第 10 章中的锁示例分为两层：
- `02_distributed_lock.py`：基础篇，使用 `redis-py Lock`
- `03_watchdog_lock_with_celery.py`：企业篇，使用 `python-redis-lock` + Celery 长任务

## Redis 连接约定

```
broker:  redis://:123456@localhost:6379/0
backend: redis://:123456@localhost:6379/1
lock:    redis://:123456@localhost:6379/2
```

分库避免 key 冲突，带密码认证。
