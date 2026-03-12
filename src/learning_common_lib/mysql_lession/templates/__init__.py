"""
SQLAlchemy 异步 ORM 企业级模板包

提供引擎、会话、模型基类、通用仓储、异常体系、FastAPI 中间件等开箱即用组件。
"""

from .db_engine import create_engine_factory, get_engine
from .db_session import get_session, async_session_factory
from .base_model import Base, TimestampMixin
from .error_registry import ErrorCode
from .error_base import (
    AppError, ClientError, ServerError,
    NotFoundError, DuplicateError, AppValidationError, OptimisticLockError,
    DatabaseError, ConnectionError,
)
from .mixins import SoftDeleteMixin, VersionMixin
from .base_repository import BaseRepository, SoftDeleteRepository, VersionedRepository

try:
    from .error_handler import ErrorResponse, register_exception_handlers, RequestIdMiddleware
except ImportError:
    ErrorResponse = None  # type: ignore[assignment]
    register_exception_handlers = None  # type: ignore[assignment]
    RequestIdMiddleware = None  # type: ignore[assignment]

__all__ = [
    # core 层 — 引擎与会话
    "create_engine_factory",
    "get_engine",
    "get_session",
    "async_session_factory",
    # core 层 — 模型与混入
    "Base",
    "TimestampMixin",
    "SoftDeleteMixin",
    "VersionMixin",
    # core 层 — 异常体系
    "ErrorCode",
    "AppError",
    "ClientError",
    "ServerError",
    "NotFoundError",
    "DuplicateError",
    "AppValidationError",
    "OptimisticLockError",
    "DatabaseError",
    "ConnectionError",
    # core 层 — 仓储
    "BaseRepository",
    "SoftDeleteRepository",
    "VersionedRepository",
    # 集成层 — FastAPI 数据库中间件（按需从 fastapi_db_middleware 显式导入）
    # from templates.fastapi_db_middleware import db_lifespan, get_db_session
]

if ErrorResponse is not None:
    __all__.extend([
        # 集成层 — FastAPI（需要 FastAPI/Pydantic 依赖）
        "ErrorResponse",
        "register_exception_handlers",
        "RequestIdMiddleware",
    ])
