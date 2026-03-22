"""
Celery 企业级模板包。

提供 async-first 的配置、App 工厂、任务基类、分布式锁与 FastAPI 集成能力。
"""

from .celery_app import (
    CUSTOM_AIO_POOL_CLASS,
    async_apply,
    async_delay,
    create_celery_app,
    get_celery_app,
    init_celery_app,
)
from .async_autoretry import async_autoretry
from .celery_config import CeleryConfig
from .distributed_lock import async_distributed_lock, distributed_lock, with_lock
from .error_handling import (
    ExternalServiceError,
    LockAcquireError,
    TaskError,
    TaskFatalError,
    TaskRateLimitError,
    TaskRetryableError,
    TaskTimeoutError,
    is_retryable,
)
from .task_base import BaseTask, async_get_result

try:
    from .fastapi_celery import (
        celery_lifespan,
        create_task_status_router,
        get_celery,
        get_redis,
        send_task,
    )
except ImportError:
    celery_lifespan = None  # type: ignore[assignment]
    get_celery = None  # type: ignore[assignment]
    get_redis = None  # type: ignore[assignment]
    send_task = None  # type: ignore[assignment]
    create_task_status_router = None  # type: ignore[assignment]

__all__ = [
    "CeleryConfig",
    "create_celery_app",
    "init_celery_app",
    "get_celery_app",
    "CUSTOM_AIO_POOL_CLASS",
    "async_delay",
    "async_apply",
    "async_autoretry",
    "TaskError",
    "TaskRetryableError",
    "TaskFatalError",
    "TaskTimeoutError",
    "TaskRateLimitError",
    "ExternalServiceError",
    "LockAcquireError",
    "is_retryable",
    "BaseTask",
    "async_get_result",
    "distributed_lock",
    "async_distributed_lock",
    "with_lock",
]

if celery_lifespan is not None:
    __all__.extend(
        [
            "celery_lifespan",
            "get_celery",
            "get_redis",
            "send_task",
            "create_task_status_router",
        ]
    )
