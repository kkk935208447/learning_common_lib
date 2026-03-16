from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    from ..config import get_settings
    from ..enums import AggregateType, OutboxEventType, PublishStatus, QueueName, TaskName
    from ..errors import FileTooLargeError, UnsupportedMediaTypeError, ValidationError
except ImportError:
    from config import get_settings
    from enums import AggregateType, OutboxEventType, PublishStatus, QueueName, TaskName
    from errors import FileTooLargeError, UnsupportedMediaTypeError, ValidationError


def utcnow():
    from datetime import datetime

    return datetime.utcnow()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build_parser_config_hash() -> str:
    settings = get_settings()
    raw = json.dumps(
        {
            "chunk_size": settings.parser_chunk_size,
            "chunk_overlap": settings.parser_chunk_overlap,
            "parser_version": settings.parser_version,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return sha256_text(raw)


def sanitize_file_name(file_name: str) -> str:
    raw_name = Path(file_name or "unnamed.txt").name.strip()
    return raw_name or "unnamed.txt"


def normalize_mime_type(mime_type: str | None) -> str:
    value = (mime_type or "application/octet-stream").strip().lower()
    return value or "application/octet-stream"


def validate_upload_request(
    *,
    external_doc_key: str,
    file_name: str,
    mime_type: str,
    content: bytes,
) -> tuple[str, str, str]:
    settings = get_settings()
    normalized_key = external_doc_key.strip()
    if not normalized_key:
        raise ValidationError("external_doc_key 不能为空")

    normalized_file_name = sanitize_file_name(file_name)
    normalized_mime_type = normalize_mime_type(mime_type)
    if normalized_mime_type not in settings.upload_allowed_mime_types:
        raise UnsupportedMediaTypeError(f"不支持的 MIME 类型: {normalized_mime_type}")
    if len(content) > settings.upload_max_bytes:
        raise FileTooLargeError(
            f"文件大小 {len(content)} bytes 超过上限 {settings.upload_max_bytes} bytes"
        )
    return normalized_key, normalized_file_name, normalized_mime_type


def build_storage_key(document_id: int, version_no: int, file_name: str) -> str:
    normalized_file_name = sanitize_file_name(file_name)
    return f"raw/document_{document_id}/version_{version_no}/{normalized_file_name}"


def chunk_text(content: str) -> list[str]:
    settings = get_settings()
    chunk_size = settings.parser_chunk_size
    overlap = settings.parser_chunk_overlap
    if chunk_size <= overlap:
        raise ValidationError("chunk_size 必须大于 chunk_overlap")

    stripped = content.strip()
    if not stripped:
        return []

    step = chunk_size - overlap
    chunks: list[str] = []
    start = 0
    while start < len(stripped):
        end = min(len(stripped), start + chunk_size)
        chunk = stripped[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def _parse_pdf_to_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValidationError("当前环境未安装 pypdf，无法解析 PDF") from exc

    reader = PdfReader(BytesIO(content))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(text.strip() for text in pages if text.strip())


def parse_bytes_to_text(content: bytes, mime_type: str) -> str:
    normalized_mime_type = normalize_mime_type(mime_type)
    if normalized_mime_type in {"text/plain", "text/markdown"}:
        return content.decode("utf-8", errors="ignore")
    if normalized_mime_type == "application/pdf":
        return _parse_pdf_to_text(content)
    raise UnsupportedMediaTypeError(f"当前 demo 不支持解析 MIME 类型: {normalized_mime_type}")


def next_retry_delay(retries: int) -> int:
    settings = get_settings()
    return settings.task_retry_base_seconds * (2 ** max(retries - 1, 0))


def build_outbox_event(
    *,
    aggregate_type: AggregateType,
    aggregate_id: int,
    event_type: OutboxEventType,
    queue_name: QueueName,
    task_name: TaskName,
    payload_json: dict[str, Any],
    dedupe_key: str,
) -> OutboxEvent:
    try:
        from ..models import OutboxEvent
    except ImportError:
        from models import OutboxEvent

    return OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        queue_name=queue_name.value,
        task_name=task_name.value,
        payload_json=payload_json,
        dedupe_key=dedupe_key,
        publish_status=PublishStatus.PENDING,
        available_at=utcnow(),
    )


def should_dispatch_event(*, publish_status: PublishStatus, next_retry_at) -> bool:
    if publish_status == PublishStatus.PENDING:
        return True
    if publish_status == PublishStatus.FAILED:
        if next_retry_at is None:
            return True
        return next_retry_at <= utcnow()
    return False
