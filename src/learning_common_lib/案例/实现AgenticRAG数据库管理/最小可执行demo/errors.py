"""Domain exceptions shared by API handlers, services, and Celery tasks."""

from __future__ import annotations


# 领域异常统一走这条继承链，便于 API 和任务层共享一套错误语义。
class DemoError(Exception):
    def __init__(self, message: str, *, code: str = "INTERNAL_ERROR") -> None:
        super().__init__(message)
        # API 层直接复用这个 code 生成统一响应，避免每个 handler 手动写映射。
        self.message = message
        self.code = code


class NotFoundError(DemoError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="NOT_FOUND")


class ConflictError(DemoError):
    # 冲突错误主要表达“状态不允许当前动作”，比如存在在途版本时重复上传。
    def __init__(self, message: str) -> None:
        super().__init__(message, code="CONFLICT")


class ValidationError(DemoError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="VALIDATION_ERROR")


class UnsupportedMediaTypeError(DemoError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="UNSUPPORTED_MEDIA_TYPE")


class FileTooLargeError(DemoError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="FILE_TOO_LARGE")


class RetryableTaskError(DemoError):
    def __init__(self, message: str) -> None:
        # 任务层看到这个错误会优先走 Celery retry，而不是直接打成最终失败。
        super().__init__(message, code="RETRYABLE_TASK_ERROR")
