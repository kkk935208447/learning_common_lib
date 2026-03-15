from __future__ import annotations

from enum import Enum


class DocumentLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELETING = "DELETING"
    DELETED = "DELETED"


class ParseStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class IndexStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ProjectionStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    DELETED = "DELETED"


class VisibilityStatus(str, Enum):
    STAGED = "STAGED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DELETE_PENDING = "DELETE_PENDING"
    DELETED = "DELETED"


class AggregateType(str, Enum):
    DOCUMENT = "DOCUMENT"
    DOCUMENT_VERSION = "DOCUMENT_VERSION"


class OutboxEventType(str, Enum):
    PARSE_REQUESTED = "PARSE_REQUESTED"
    INDEX_REQUESTED = "INDEX_REQUESTED"
    CLEAN_REQUESTED = "CLEAN_REQUESTED"
    REBUILD_REQUESTED = "REBUILD_REQUESTED"


class PublishStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class QueueName(str, Enum):
    PARSE = "parse_jobs"
    INDEX = "index_jobs"
    CLEAN = "clean_jobs"
    REPAIR = "repair_jobs"
    HOUSEKEEPING = "housekeeping_jobs"


class TaskName(str, Enum):
    PARSE_VERSION = "min_rag_demo.parse_version"
    INDEX_VERSION = "min_rag_demo.index_version"
    CLEAN_VERSION = "min_rag_demo.clean_version"
    DISPATCH_OUTBOX = "min_rag_demo.dispatch_outbox"
    JANITOR_SCAN = "min_rag_demo.janitor_scan"
    CLEAN_OUTBOX = "min_rag_demo.clean_outbox"
