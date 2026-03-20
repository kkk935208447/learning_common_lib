"""Small helpers shared by services, workers, and scripts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.utcnow()


def new_request_id() -> str:
    return f"req_{uuid4().hex[:16]}"


def new_execution_id(*, task_id: int, plan_version: int, subtask_code: str) -> str:
    return f"exec:{task_id}:{plan_version}:{subtask_code}:{uuid4().hex[:12]}"


def hash_json(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_thread_id(task_id: int) -> str:
    return f"deepsearch:task:{task_id}"
