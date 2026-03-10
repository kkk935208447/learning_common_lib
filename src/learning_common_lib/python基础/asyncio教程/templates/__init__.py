"""企业级异步模板包。

用法（从 asyncio教程/ 目录或将其加入 sys.path）：

    from templates.result_types import TaskResult
    from templates.executor import AsyncExecutor
    from templates.retry import retry_with_backoff
    from templates.background_tasks import BackgroundTaskManager
    from templates.shutdown import GracefulShutdown
"""

from .background_tasks import BackgroundTaskManager
from .executor import AsyncExecutor
from .result_types import TaskResult
from .retry import retry_with_backoff
from .shutdown import GracefulShutdown

__all__ = [
    "AsyncExecutor",
    "BackgroundTaskManager",
    "GracefulShutdown",
    "TaskResult",
    "retry_with_backoff",
]
