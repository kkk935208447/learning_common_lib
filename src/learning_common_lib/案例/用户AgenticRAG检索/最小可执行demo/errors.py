"""Shared domain errors for the deepsearch minimum demo."""

from __future__ import annotations


class DeepSearchError(Exception):
    code = "DEEPSEARCH_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


DemoError = DeepSearchError


class NotFoundError(DeepSearchError):
    code = "NOT_FOUND"


class ConflictError(DeepSearchError):
    code = "CONFLICT"


class ValidationError(DeepSearchError):
    code = "VALIDATION_ERROR"


class StaleExecutionError(DeepSearchError):
    code = "STALE_EXECUTION"


class RetryableDispatchError(DeepSearchError):
    code = "RETRYABLE_DISPATCH_ERROR"
