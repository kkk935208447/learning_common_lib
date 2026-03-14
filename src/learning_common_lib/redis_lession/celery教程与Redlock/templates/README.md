# Celery + Redis 分布式锁企业级模板包

这是一套 async-first 的 Celery 企业模板包，默认围绕 `custom aio pool + async def task` 设计，覆盖配置管理、任务基类、异常体系、分布式锁和 FastAPI 集成。

## 使用方式

将 `templates/` 目录复制到你的项目中，通过环境变量 `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` / `CELERY_CUSTOM_WORKER_POOL` 配置 Redis 连接与 worker pool。锁模板依赖 `python-redis-lock`，适合需要自动续期的 Celery 长任务。每个模板文件底部都有 `_demo()` 函数，可直接运行查看效果。

推荐 worker 启动方式：

```bash
CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool' \
celery -A myproj.celery_app:app worker -P custom -Q aio_jobs --loglevel=info -c 20
```

## 分层设计

模板分为 core 层和集成层：

- **core 层**：`celery_config`, `celery_app`, `error_handling`, `task_base`, `distributed_lock`
- **集成层**：`fastapi_celery`

如果环境里没有安装 FastAPI，core 层仍可正常使用。

```python
from templates import (
    CeleryConfig,
    CUSTOM_AIO_POOL_CLASS,
    create_celery_app,
    init_celery_app,
    get_celery_app,
    async_delay,
    async_apply,
    TaskError,
    TaskRetryableError,
    TaskFatalError,
    TaskTimeoutError,
    TaskRateLimitError,
    ExternalServiceError,
    LockAcquireError,
    is_retryable,
    BaseTask,
    async_get_result,
    distributed_lock,
    async_distributed_lock,
    with_lock,
)
```

## 模块说明

| 文件 | 说明 |
|------|------|
| `__init__.py` | async-first 公开 API 导出 |
| `celery_config.py` | async-first 配置对象，包含 `custom aio pool` 约定 |
| `celery_app.py` | App 工厂、单例管理、producer 侧 async 包装 |
| `error_handling.py` | 异常层级树，区分可重试/不可重试 |
| `task_base.py` | async-first 任务基类，统一生命周期回调、日志、重试决策 |
| `distributed_lock.py` | 企业级分布式锁，默认推荐 `async_distributed_lock()` |
| `fastapi_celery.py` | FastAPI 集成：lifespan、依赖注入、任务派发、状态轮询 |

## 决策表

| 场景 | 使用模板 | 说明 |
|------|---------|------|
| 新项目初始化 Celery | `celery_config` + `celery_app` | 先配置，再建 App |
| async-first 任务日志和重试 | `task_base` + `error_handling` | `BaseTask` 默认面向 `async def task` |
| Celery 长任务锁保护 | `distributed_lock` | 默认推荐 `async_distributed_lock()` |
| FastAPI 项目集成 Celery | `fastapi_celery` | producer 侧继续保留 `to_thread` 兼容包装 |
| 只需要异常分类 | `error_handling` | 独立使用，不依赖其他模板 |

## 推荐阅读顺序

1. `celery_config.py` — async-first 配置项与 worker 约定
2. `celery_app.py` — App 工厂和 producer 侧兼容包装
3. `error_handling.py` — 异常层级和重试决策
4. `task_base.py` — async-first 任务基类与 `safe_run()`
5. `distributed_lock.py` — async 锁与看门狗续期
6. `fastapi_celery.py` — FastAPI 集成全貌

## 生产环境 checklist

- [ ] `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` 通过环境变量配置，不硬编码
- [ ] `CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool'` 已配置
- [ ] worker 使用 `-P custom` 启动
- [ ] `task_soft_time_limit` / `task_time_limit` 根据业务调整
- [ ] `task_acks_late=True` + `task_reject_on_worker_lost=True` 已开启
- [ ] `worker_prefetch_multiplier=1` 已设置
- [ ] 所有主线任务优先使用 `async def` + `BaseTask`
- [ ] 可重试异常继承 `TaskRetryableError`，不可重试异常继承 `TaskFatalError`
- [ ] 分布式锁的 `timeout` 大于临界区最大执行时间
- [ ] Celery 长任务优先开启 `auto_renewal=True`
- [ ] FastAPI 通过 `send_task()` / 状态路由与 Celery 交互
- [ ] 接受 producer 侧 `to_thread` 是客户端兼容层，不把它误解为 worker 未 async 化
- [ ] Redis 连接配置了密码和 TLS（生产环境）
- [ ] Worker 部署使用 supervisor / systemd 管理进程
