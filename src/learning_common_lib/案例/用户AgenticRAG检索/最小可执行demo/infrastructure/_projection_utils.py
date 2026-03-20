"""Shared helpers for file-based retrieval adapters."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


TOKEN_PATTERN = re.compile(r"[0-9a-zA-Z_\u4e00-\u9fff]+")


def load_json_records(root_dir: Path) -> list[dict]:
    records: list[dict] = []
    for path in sorted(root_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload["_path"] = str(path)
        records.append(payload)
    return records


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text or "")]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(x * y for x, y in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(x * x for x in left))
    right_norm = math.sqrt(sum(y * y for y in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def bm25_lite_score(query: str, content: str) -> float:
    query_tokens = tokenize(query)
    content_tokens = tokenize(content)
    if not query_tokens or not content_tokens:
        return 0.0
    content_set = set(content_tokens)
    overlap = sum(1 for token in query_tokens if token in content_set)
    phrase_bonus = 1.0 if query.strip() and query.strip().lower() in content.lower() else 0.0
    return (overlap / len(query_tokens)) + (phrase_bonus * 0.1)
