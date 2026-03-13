"""
Celery + Redlock 企业级模板包

提供 Celery 配置、App 工厂、异常体系、任务基类、分布式锁、FastAPI 集成等开箱即用组件。
"""

# --- core 层 — 配置 ---
from .celery_config import CeleryConfig

# --- core 层 — App 工厂与单例 ---
from .celery_app import (
    create_celery_app,
    init_celery_app,
    get_celery_app,
    async_delay,
    async_apply,
)

# --- core 层 — 异常体系 ---
from .error_handling import (
    TaskError,
    TaskRetryableError,
    TaskFatalError,
    TaskTimeoutError,
    TaskRateLimitError,
    ExternalServiceError,
    LockAcquireError,
    is_retryable,
)

# --- core 层 — 任务基类 ---
from .task_base import BaseTask, async_get_result

# --- core 层 — 分布式锁 ---
from .redlock import (
    distributed_lock,
    async_distributed_lock,
    with_lock,
)

# --- 集成层 — FastAPI（需要 FastAPI 依赖） ---
try:
    from .fastapi_celery import (
        celery_lifespan,
        get_celery,
        get_redis,
        send_task,
        create_task_status_router,
    )
except ImportError:
    celery_lifespan = None  # type: ignore[assignment]
    get_celery = None  # type: ignore[assignment]
    get_redis = None  # type: ignore[assignment]
    send_task = None  # type: ignore[assignment]
    create_task_status_router = None  # type: ignore[assignment]


__all__ = [
    # core 层 — 配置
    "CeleryConfig",
    # core 层 — App 工厂与单例
    "create_celery_app",
    "init_celery_app",
    "get_celery_app",
    "async_delay",
    "async_apply",
    # core 层 — 异常体系
    "TaskError",
    "TaskRetryableError",
    "TaskFatalError",
    "TaskTimeoutError",
    "TaskRateLimitError",
    "ExternalServiceError",
    "LockAcquireError",
    "is_retryable",
    # core 层 — 任务基类
    "BaseTask",
    "async_get_result",
    # core 层 — 分布式锁
    "distributed_lock",
    "async_distributed_lock",
    "with_lock",
]

if celery_lifespan is not None:
    __all__.extend([
        # 集成层 — FastAPI（需要 FastAPI 依赖）
        "celery_lifespan",
        "get_celery",
        "get_redis",
        "send_task",
        "create_task_status_router",
    ])
