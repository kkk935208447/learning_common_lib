"""
SQLAlchemy 异步 ORM 企业级模板包

提供引擎、会话、模型基类、通用仓储、异常体系、FastAPI 中间件等开箱即用组件。

分层设计:
  core 层（无 FastAPI/Pydantic 依赖）: error_registry, error_base, mixins, base_model, base_repository
  集成层（需要 FastAPI/Pydantic）: error_handler, fastapi_db_middleware

  默认导出 core 层所有符号。FastAPI 集成层按需显式导入:
    from templates.error_handler import register_exception_handlers, RequestIdMiddleware, ErrorResponse
    from templates.fastapi_db_middleware import db_lifespan, get_db_session
"""

# --- core 层：无 FastAPI/Pydantic 依赖 ---
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


# --- 集成层：懒加载，避免强制依赖 FastAPI/Pydantic ---
def __getattr__(name: str):
    _fastapi_symbols = {
        "ErrorResponse", "register_exception_handlers", "RequestIdMiddleware",
    }
    if name in _fastapi_symbols:
        from . import error_handler
        return getattr(error_handler, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

