"""Small helpers shared by services, workers, and scripts."""

from __future__ import annotations

import hashlib
import json

try:
    from .application.common import build_execution_id, build_request_id, utcnow
except ImportError:
    from 最小可执行demo.application.common import build_execution_id, build_request_id, utcnow


def new_request_id() -> str:
    return build_request_id("compat", "compat")


def new_execution_id(*, task_id: int, plan_version: int, subtask_code: str) -> str:
    return build_execution_id(task_id, plan_version, subtask_code, 0)


def hash_json(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_thread_id(task_id: int) -> str:
    return f"deepsearch:task:{task_id}"
