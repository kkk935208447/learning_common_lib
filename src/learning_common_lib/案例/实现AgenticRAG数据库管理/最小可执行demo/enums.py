"""Domain status enums used by the minimal Agentic RAG demo."""

from __future__ import annotations

from enum import Enum


# 所有跨模块共享的状态值都集中放这里，避免服务层散落字符串字面量。
class DocumentLifecycleStatus(str, Enum):
    # 面向 document 级别的生命周期：逻辑文档是否仍对外存在。
    ACTIVE = "ACTIVE"
    DELETING = "DELETING"
    DELETED = "DELETED"


class ParseStatus(str, Enum):
    # 面向 parse 阶段的流水线状态。
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class IndexStatus(str, Enum):
    # 面向 index 阶段的流水线状态。
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ProjectionStatus(str, Enum):
    # 面向外部投影（Milvus/ES mock）的状态。
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    DELETED = "DELETED"


class StorageStatus(str, Enum):
    # 面向对象存储源文件的状态。
    PENDING_UPLOAD = "PENDING_UPLOAD"
    READY = "READY"
    DELETE_PENDING = "DELETE_PENDING"
    DELETED = "DELETED"
    FAILED = "FAILED"


class VisibilityStatus(str, Enum):
    # 面向读路径的可见性状态：是否 staged/active/superseded/deleted。
    STAGED = "STAGED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DELETE_PENDING = "DELETE_PENDING"
    DELETED = "DELETED"


class AggregateType(str, Enum):
    # aggregate_type 让 Outbox 事件能标明自己附着在哪类实体上。
    DOCUMENT = "DOCUMENT"
    DOCUMENT_VERSION = "DOCUMENT_VERSION"


class OutboxEventType(str, Enum):
    PARSE_REQUESTED = "PARSE_REQUESTED"
    INDEX_REQUESTED = "INDEX_REQUESTED"
    CLEAN_REQUESTED = "CLEAN_REQUESTED"
    REBUILD_REQUESTED = "REBUILD_REQUESTED"


class PublishStatus(str, Enum):
    # PENDING 表示从未投递，FAILED 表示投递过但需要等待重试窗口。
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"

class QueueName(str, Enum):
    # Celery 队列名直接放在这里，读 Celery 配置时不需要再跳文件。
    # 这也让 Outbox 事件写入时可以使用强约束枚举，而不是裸字符串。
    PARSE = "parse_jobs"
    INDEX = "index_jobs"
    CLEAN = "clean_jobs"
    REPAIR = "repair_jobs"
    HOUSEKEEPING = "housekeeping_jobs"


class TaskName(str, Enum):
    # task 名称保留统一前缀，方便在 worker 日志里快速筛选。
    # 这里的值既是 Celery 注册名，也是 Outbox 中写入的 task_name。
    PARSE_VERSION = "min_rag_demo.parse_version"
    INDEX_VERSION = "min_rag_demo.index_version"
    CLEAN_VERSION = "min_rag_demo.clean_version"
    DISPATCH_OUTBOX = "min_rag_demo.dispatch_outbox"
    JANITOR_SCAN = "min_rag_demo.janitor_scan"
    CLEAN_OUTBOX = "min_rag_demo.clean_outbox"
