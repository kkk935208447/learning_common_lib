# Celery + Redis 分布式锁企业级模板包

这是一套企业级 Celery + Redis 分布式锁模板包，提供从配置管理到 FastAPI 集成的完整解决方案，包含异常体系、任务基类、分布式锁等企业级模式。

## 使用方式

将 `templates/` 目录复制到你的项目中，通过环境变量 `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` 配置 Redis 连接。锁模板依赖 `python-redis-lock`，适合需要自动续期的 Celery 长任务。每个模板文件底部都有 `_demo()` 函数，可直接运行查看效果。

## 分层设计

模板分为 core 层和集成层，便于理解复用边界：

- **core 层**（无 FastAPI 依赖）：`celery_config`, `celery_app`, `error_handling`, `task_base`, `distributed_lock`
- **集成层**（需要 FastAPI）：`fastapi_celery`

当前实现已把 FastAPI 集成符号做成可选导入；如果环境里没有安装 FastAPI，core 层仍可正常使用。

```python
# core 层 — 任何项目都能用
from templates import (
    # 配置
    CeleryConfig,
    # App 工厂与单例
    create_celery_app, init_celery_app, get_celery_app, async_delay, async_apply,
    # 异常体系
    TaskError, TaskRetryableError, TaskFatalError, TaskTimeoutError,
    TaskRateLimitError, ExternalServiceError, LockAcquireError, is_retryable,
    # 任务基类
    BaseTask, async_get_result,
    # 分布式锁
    distributed_lock, async_distributed_lock, with_lock,
)

# 集成层 — 仅 FastAPI 项目需要
from templates.fastapi_celery import (
    celery_lifespan, get_celery, get_redis, send_task, create_task_status_router,
)
```

## 模块说明

| 文件 | 说明 |
|------|------|
| `__init__.py` | 公开 API 导出，分 core 层和集成层，附 `__all__` 列表 |
| `celery_config.py` | 生产级配置类，涵盖序列化、超时、限流、可靠投递等关键参数 |
| `celery_app.py` | App 工厂 + 单例管理 + 异步包装（async_delay / async_apply） |
| `error_handling.py` | 任务异常层级树，区分可重试/不可重试，统一重试决策 |
| `task_base.py` | 任务基类，统一生命周期回调、结构化日志、异常重试决策 |
| `distributed_lock.py` | 企业级分布式锁：基于 `python-redis-lock`，默认开启看门狗自动续期；`async_distributed_lock` 为线程池包装 |
| `redlock.py` | 历史兼容别名，内部转发到 `distributed_lock.py` |
| `fastapi_celery.py` | FastAPI 集成：lifespan、依赖注入、异步派发、状态轮询 |

## 依赖关系

```
celery_config ← celery_app
error_handling ← task_base
error_handling ← distributed_lock (LockAcquireError)
celery_app ← fastapi_celery
distributed_lock ← fastapi_celery
```

箭头表示"被依赖"：`A ← B` 意味着 B 导入了 A。

完整依赖图：

```
┌────────────────┐
│ celery_config  │
└───────┬────────┘
        │
┌───────▼────────┐     ┌─────────────────┐
│  celery_app    │     │ error_handling   │
└───────┬────────┘     └──┬──────────┬───┘
        │                 │          │
        │          ┌──────▼───┐  ┌───▼────────────┐
        │          │ task_base │  │ distributed_lock │
        │          └──────────┘  └───┬───────┘
        │                            │
┌───────▼────────────────────────────▼───┐
│          fastapi_celery                │
└────────────────────────────────────────┘
```

## 决策表：何时使用哪个模板

| 场景 | 使用模板 | 说明 |
|------|---------|------|
| 新项目初始化 Celery | `celery_config` + `celery_app` | 先配置，再建 App |
| 需要统一任务日志和重试 | `task_base` + `error_handling` | BaseTask 自动处理回调和重试决策 |
| 防止并发竞争（如订单处理） | `distributed_lock` | 默认使用 `python-redis-lock` 的自动续期能力 |
| FastAPI 项目集成 Celery | `fastapi_celery` | lifespan + Depends + 状态轮询 |
| 只需要异常分类 | `error_handling` | 独立使用，不依赖其他模板 |
| 需要在 asyncio 中调用 Celery | `celery_app` (async_delay/async_apply) | asyncio.to_thread 包装 |
| 自定义配置（开发/测试） | 继承 `CeleryConfig` 覆盖属性 | 如 `broker_url`、`result_backend` 等 |

## 推荐阅读顺序

1. `celery_config.py` — 配置项和含义
2. `celery_app.py` — App 工厂和单例
3. `error_handling.py` — 异常层级和重试决策
4. `task_base.py` — 任务基类和生命周期回调
5. `distributed_lock.py` — 企业级分布式锁与自动续期
6. `fastapi_celery.py` — FastAPI 集成全貌

## 生产环境 checklist

- [ ] `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` 通过环境变量配置，不硬编码
- [ ] `task_soft_time_limit` / `task_time_limit` 根据业务调整
- [ ] `task_acks_late=True` + `task_reject_on_worker_lost=True` 已开启（可靠投递）
- [ ] `worker_prefetch_multiplier=1` 已设置（公平调度）
- [ ] 所有任务继承 `BaseTask`，统一日志和重试策略
- [ ] 可重试异常继承 `TaskRetryableError`，不可重试继承 `TaskFatalError`
- [ ] 分布式锁的 `timeout` 大于临界区最大执行时间
- [ ] 分布式锁的 `blocking_timeout` 根据业务容忍度设置
- [ ] Celery 长任务优先开启 `auto_renewal=True`，不要只依赖固定 TTL
- [ ] 如需兼容旧示例，可继续使用 `redlock.py`，但新代码统一从 `distributed_lock.py` 导入
- [ ] FastAPI 使用 `celery_lifespan` 管理生命周期
- [ ] 任务状态轮询有前端配合的退避策略（避免高频轮询）
- [ ] Redis 连接配置了密码和 TLS（生产环境）
- [ ] Worker 部署使用 supervisor / systemd 管理进程
