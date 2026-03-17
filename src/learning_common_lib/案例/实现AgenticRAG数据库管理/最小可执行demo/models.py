"""SQLAlchemy ORM models for documents, versions, chunks, and Outbox events."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, JSON, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

try:
    from .enums import (
        AggregateType,
        DocumentLifecycleStatus,
        IndexStatus,
        OutboxEventType,
        ParseStatus,
        ProjectionStatus,
        PublishStatus,
        StorageStatus,
        VisibilityStatus,
    )
except ImportError:
    from enums import (
        AggregateType,
        DocumentLifecycleStatus,
        IndexStatus,
        OutboxEventType,
        ParseStatus,
        ProjectionStatus,
        PublishStatus,
        StorageStatus,
        VisibilityStatus,
    )


class Base(DeclarativeBase):
    pass


# 共享时间戳 mixin，避免 4 张核心表重复声明相同列。
class TimestampMixin:
    # 所有核心表统一带上 created_at / updated_at，方便演示状态推进时间线。
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Document(TimestampMixin, Base):
    __tablename__ = "rag_min_demo_documents"

    # Document 表只表达“逻辑文档身份”，不直接承载解析和索引流水线状态。
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_doc_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    lifecycle_status: Mapped[DocumentLifecycleStatus] = mapped_column(
        Enum(DocumentLifecycleStatus),
        default=DocumentLifecycleStatus.ACTIVE,
        nullable=False,
    )
    active_version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    latest_version_no: Mapped[int] = mapped_column(default=0, nullable=False)
    row_version: Mapped[int] = mapped_column(default=0, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DocumentVersion(TimestampMixin, Base):
    __tablename__ = "rag_min_demo_document_versions"
    __table_args__ = (
        # 同一个逻辑文档内部，版本号必须单调唯一。
        UniqueConstraint("document_id", "version_no", name="uq_rag_min_demo_doc_versions_doc_ver"),
        Index(
            "idx_rag_min_demo_doc_versions_doc_file_hash",
            "document_id",
            "file_hash",
        ),
        # 教学 demo 把常见状态查询聚合进一个复合索引，方便解释“版本状态就是主观测面”。
        Index(
            "idx_rag_min_demo_doc_versions_status",
            "parse_status",
            "index_status",
            "visibility_status",
            "storage_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("rag_min_demo_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_status: Mapped[StorageStatus] = mapped_column(
        Enum(StorageStatus),
        default=StorageStatus.PENDING_UPLOAD,
        nullable=False,
    )
    parse_status: Mapped[ParseStatus] = mapped_column(Enum(ParseStatus), default=ParseStatus.PENDING, nullable=False)
    index_status: Mapped[IndexStatus] = mapped_column(Enum(IndexStatus), default=IndexStatus.PENDING, nullable=False)
    milvus_status: Mapped[ProjectionStatus] = mapped_column(
        Enum(ProjectionStatus),
        default=ProjectionStatus.PENDING,
        nullable=False,
    )
    es_status: Mapped[ProjectionStatus] = mapped_column(
        Enum(ProjectionStatus),
        default=ProjectionStatus.PENDING,
        nullable=False,
    )
    visibility_status: Mapped[VisibilityStatus] = mapped_column(
        Enum(VisibilityStatus),
        default=VisibilityStatus.STAGED,
        nullable=False,
    )
    chunk_count: Mapped[int] = mapped_column(default=0, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    last_error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    # row_version 在 demo 里主要用来显式呈现状态变更次数，方便观察并发更新。
    row_version: Mapped[int] = mapped_column(default=0, nullable=False)


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "rag_min_demo_document_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "chunk_no", name="uq_rag_min_demo_chunks_ver_chunk"),
    )

    # Chunk 表保存的是 MySQL 中的事实数据，向量库和搜索库都可以从这里重建。
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("rag_min_demo_document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_uid: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    chunk_no: Mapped[int] = mapped_column(nullable=False)
    chunk_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class OutboxEvent(TimestampMixin, Base):
    __tablename__ = "rag_min_demo_outbox_events"

    # Outbox 是“业务提交成功”与“异步派发成功”之间的缓冲层。
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aggregate_type: Mapped[AggregateType] = mapped_column(Enum(AggregateType), nullable=False)
    aggregate_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[OutboxEventType] = mapped_column(Enum(OutboxEventType), nullable=False)
    queue_name: Mapped[str] = mapped_column(String(64), nullable=False)
    task_name: Mapped[str] = mapped_column(String(128), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    publish_status: Mapped[PublishStatus] = mapped_column(
        Enum(PublishStatus),
        default=PublishStatus.PENDING,
        nullable=False,
    )
    # 可用时间与下次重试时间分开保存，便于 Dispatcher 统一处理首次投递和失败重试。
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
