"""
TaskIQ 企业级模板包。

提供 async-first 的配置、Broker 工厂、异常层级、任务装饰器、中间件栈与 FastAPI 集成能力。
"""

from .error_handling import (
    ExternalServiceError,
    TaskError,
    TaskFatalError,
    TaskRateLimitError,
    TaskRetryableError,
    TaskTimeoutError,
    is_retryable,
)
from .middleware_stack import (
    LoggingMiddleware,
    RetryMiddleware,
    TimeoutMiddleware,
    create_default_middlewares,
)
from .task_base import create_task, safe_execute
from .taskiq_app import create_taskiq_broker, get_broker, init_broker
from .taskiq_config import TaskiqConfig

try:
    from .fastapi_taskiq import (
        TaskResponse,
        get_broker as get_fastapi_broker,
        send_task,
        taskiq_lifespan,
    )
except ImportError:
    taskiq_lifespan = None  # type: ignore[assignment]
    get_fastapi_broker = None  # type: ignore[assignment]
    send_task = None  # type: ignore[assignment]
    TaskResponse = None  # type: ignore[assignment]

__all__ = [
    "TaskiqConfig",
    "create_taskiq_broker",
    "init_broker",
    "get_broker",
    "TaskError",
    "TaskRetryableError",
    "TaskFatalError",
    "TaskTimeoutError",
    "TaskRateLimitError",
    "ExternalServiceError",
    "is_retryable",
    "create_task",
    "safe_execute",
    "LoggingMiddleware",
    "RetryMiddleware",
    "TimeoutMiddleware",
    "create_default_middlewares",
]

if taskiq_lifespan is not None:
    __all__.extend(
        [
            "taskiq_lifespan",
            "get_fastapi_broker",
            "send_task",
            "TaskResponse",
        ]
    )
