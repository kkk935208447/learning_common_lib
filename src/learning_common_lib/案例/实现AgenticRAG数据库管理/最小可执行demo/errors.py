from __future__ import annotations


class DemoError(Exception):
    def __init__(self, message: str, *, code: str = "INTERNAL_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class NotFoundError(DemoError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="NOT_FOUND")


class ConflictError(DemoError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="CONFLICT")


class ValidationError(DemoError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="VALIDATION_ERROR")


class RetryableTaskError(DemoError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="RETRYABLE_TASK_ERROR")
