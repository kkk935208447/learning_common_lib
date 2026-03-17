"""Pydantic schemas for API responses and demo management endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


# VersionRead 面向运维排查，字段刻意比在线读路径更完整。
class VersionRead(BaseModel):
    id: int
    document_id: int
    version_no: int
    file_hash: str
    file_name: str
    file_size: int
    mime_type: str
    storage_key: str
    storage_status: str
    parse_status: str
    index_status: str
    milvus_status: str
    es_status: str
    visibility_status: str
    chunk_count: int
    retry_count: int
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime

    # 允许直接从 ORM 对象构造，减少 API 层手写字段搬运。
    # 同时也能让 demo 在 schema 变更时更容易发现字段遗漏。
    model_config = {"from_attributes": True}


class DocumentRead(BaseModel):
    # 文档详情响应会内嵌版本列表，便于 demo 页面或脚本一次性观察状态。
    id: int
    external_doc_key: str
    title: str
    lifecycle_status: str
    active_version_id: int | None
    latest_version_no: int
    created_at: datetime
    updated_at: datetime
    versions: list[VersionRead]


class UploadResult(BaseModel):
    # 上传结果只返回主键和复用信息，避免接口首响应耦合后续异步状态。
    document_id: int
    version_id: int
    reused_existing_version: bool
    message: str


class OutboxEventRead(BaseModel):
    # Outbox 观察接口只暴露调度相关字段，不需要原样返回 payload_json。
    id: int
    aggregate_type: str
    aggregate_id: int
    event_type: str
    queue_name: str
    task_name: str
    dedupe_key: str
    publish_status: str
    available_at: datetime
    next_retry_at: datetime | None
    published_at: datetime | None

    # Outbox ORM 对象可以直接喂给 schema，省掉管理接口层的手工映射。
    model_config = {"from_attributes": True}


class AdminStatsRead(BaseModel):
    # 管理统计只保留最小观测指标，足够演示“系统是否堆积/失败”。
    outbox_pending_count: int
    parse_failed_count: int
    index_failed_count: int
    active_version_count: int


class OkResponse(BaseModel):
    # 这里只是把统一响应结构显式写出来，当前 API 仍主要通过 `ok(...)` 帮助函数返回。
    code: str = "OK"
    message: str = "success"
    data: dict | list | None = None
