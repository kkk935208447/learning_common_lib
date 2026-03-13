# Celery 教程与 Redlock 分布式锁

## 定位

从零掌握 Celery 分布式任务队列 + Redis 分布式锁，覆盖配置、任务定义、调用、结果、重试、路由、定时、工作流、监控、FastAPI 集成共 10 章渐进式示例，外加一套企业级可复用模板。

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
uv add "celery[redis]" "redis>=5.0" flower fastapi uvicorn
```

## 目录结构

```
celery教程与Redlock/
├── README.md                ← 本文件
├── roadmap.md               ← 学习路线
├── architecture_map.md      ← 架构全景图
├── best_practices.md        ← 最佳实践
├── pitfalls.md              ← 常见陷阱
├── smoke/
│   └── run_all_examples.py  ← 一键验证所有示例
├── examples/
│   ├── 01_app_and_config/   ← Celery 实例与配置
│   ├── 02_task_definition/  ← 任务定义
│   ├── 03_task_invocation/  ← 任务调用
│   ├── 04_result_backend/   ← 结果后端
│   ├── 05_error_handling/   ← 错误与重试
│   ├── 06_routing_and_queues/ ← 路由与队列
│   ├── 07_periodic_tasks/   ← 定时任务
│   ├── 08_workflows/        ← 工作流编排
│   ├── 09_signals_and_monitoring/ ← 信号与监控
│   └── 10_fastapi_integration/   ← FastAPI + Redlock
└── templates/
    ├── celery_config.py     ← 生产级配置
    ├── celery_app.py        ← App 工厂 + 异步包装
    ├── task_base.py         ← 基础任务类
    ├── error_handling.py    ← 异常层级树
    ├── redlock.py           ← 分布式锁
    └── fastapi_celery.py    ← FastAPI 集成
```

## 快速开始

```bash
cd src/learning_common_lib/redis_lession/celery教程与Redlock

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

## 学习路线概览

| 章 | 主题 | 核心知识点 |
|----|------|-----------|
| 01 | App 与配置 | Celery 实例创建、broker/backend 角色、配置方式对比 |
| 02 | 任务定义 | @app.task 参数、bind=True、序列化约束 |
| 03 | 任务调用 | delay/apply_async、Signature、countdown/ETA |
| 04 | 结果后端 | AsyncResult 状态机、result_expires |
| 05 | 错误与重试 | self.retry()、autoretry_for、指数退避 |
| 06 | 路由与队列 | 多队列分流、task_routes、优先级队列 |
| 07 | 定时任务 | Celery Beat、crontab、动态调度 |
| 08 | 工作流 | chain/group/chord/chunks |
| 09 | 信号与监控 | task signals、Flower、自定义事件 |
| 10 | FastAPI 集成 | 触发任务/轮询状态/Redlock 分布式锁 |

## Redis 连接约定

```
broker:  redis://:123456@localhost:6379/0
backend: redis://:123456@localhost:6379/1
```

分库避免 key 冲突，带密码认证。
