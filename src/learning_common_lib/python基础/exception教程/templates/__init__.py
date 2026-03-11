"""企业级异常处理模板包。

用法（从 exception教程/ 目录或将其加入 sys.path）：

    from templates.error_base import AppError, NotFoundError, DatabaseError
    from templates.error_registry import ErrorCode
    from templates.error_context import ErrorContext, error_context
    from templates.fastapi_error_handler import register_exception_handlers
"""

from .error_base import (
    AppError,
    AppValidationError,
    AuthenticationError,
    ClientError,
    ConflictError,
    DatabaseError,
    ExternalServiceError,
    GatewayTimeoutError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    ServerError,
)
from .error_context import ErrorContext, error_context, get_context, reset_context, set_context
from .error_registry import ErrorCode
from .fastapi_error_handler import ErrorResponse, register_exception_handlers

__all__ = [
    "AppError",
    "AppValidationError",
    "AuthenticationError",
    "ClientError",
    "ConflictError",
    "DatabaseError",
    "ErrorCode",
    "ErrorContext",
    "ErrorResponse",
    "ExternalServiceError",
    "GatewayTimeoutError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitedError",
    "ServerError",
    "error_context",
    "get_context",
    "register_exception_handlers",
    "reset_context",
    "set_context",
]
