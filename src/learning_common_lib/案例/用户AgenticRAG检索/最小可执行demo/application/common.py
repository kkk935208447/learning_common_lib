"""Shared helpers for application services."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any


def utcnow() -> datetime:
    return datetime.utcnow()


def value_of(value: Any) -> Any:
    return getattr(value, "value", value)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value_of(value)


def build_request_id(session_id: str, query: str) -> str:
    suffix = hashlib.sha256(f"{session_id}:{query}:{utcnow().isoformat()}".encode("utf-8")).hexdigest()[:12]
    return f"req_{suffix}"


def build_execution_id(task_id: int, plan_version: int, subtask_code: str, attempt_no: int) -> str:
    return f"exec_{task_id}_{plan_version}_{subtask_code}_{attempt_no}"

