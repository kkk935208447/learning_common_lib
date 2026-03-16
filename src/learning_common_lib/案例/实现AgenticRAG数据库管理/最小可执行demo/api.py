"""FastAPI entrypoint that exposes upload, status, and ops endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from .bootstrap import build_object_storage, build_search_store, build_task_queue, build_vector_store
    from .config import get_settings
    from .db import create_tables, dispose_engine, get_db_session, session_scope
    from .enums import IndexStatus, ParseStatus
    from .errors import (
        ConflictError,
        DemoError,
        FileTooLargeError,
        NotFoundError,
        UnsupportedMediaTypeError,
        ValidationError,
    )
    from .repositories import DocumentRepository, OutboxRepository, VersionRepository
    from .schemas import AdminStatsRead, DocumentRead, OutboxEventRead, UploadResult, VersionRead
    from .services import DocumentCommandService, JanitorService, OutboxDispatcherService, best_effort_dispatch_outbox
except ImportError:
    from bootstrap import build_object_storage, build_search_store, build_task_queue, build_vector_store
    from config import get_settings
    from db import create_tables, dispose_engine, get_db_session, session_scope
    from enums import IndexStatus, ParseStatus
    from errors import (
        ConflictError,
        DemoError,
        FileTooLargeError,
        NotFoundError,
        UnsupportedMediaTypeError,
        ValidationError,
    )
    from repositories import DocumentRepository, OutboxRepository, VersionRepository
    from schemas import AdminStatsRead, DocumentRead, OutboxEventRead, UploadResult, VersionRead
    from services import DocumentCommandService, JanitorService, OutboxDispatcherService, best_effort_dispatch_outbox


def ok(data: Any = None, message: str = "success") -> dict[str, Any]:
    return {"code": "OK", "message": message, "data": data}


async def load_document_detail(session: AsyncSession, document_id: int) -> DocumentRead:
    doc_repo = DocumentRepository(session)
    version_repo = VersionRepository(session)
    document = await doc_repo.get_by_id(document_id)
    if document is None:
        raise NotFoundError(f"document {document_id} 不存在")
    versions = await version_repo.list_by_document(document_id)
    return DocumentRead(
        id=document.id,
        external_doc_key=document.external_doc_key,
        title=document.title,
        lifecycle_status=document.lifecycle_status.value,
        active_version_id=document.active_version_id,
        latest_version_no=document.latest_version_no,
        created_at=document.created_at,
        updated_at=document.updated_at,
        versions=[VersionRead.model_validate(version) for version in versions],
    )


async def load_version_detail(session: AsyncSession, version_id: int) -> VersionRead:
    version_repo = VersionRepository(session)
    version = await version_repo.get_by_id(version_id)
    if version is None:
        raise NotFoundError(f"version {version_id} 不存在")
    return VersionRead.model_validate(version)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_settings().auto_create_tables_on_startup:
        # 默认关闭自动建表；这里只给需要“一键起 demo”的场景留一个后门。
        await create_tables()
    try:
        yield
    finally:
        await dispose_engine()


app = FastAPI(title="Agentic RAG Min Demo", lifespan=lifespan)


@app.exception_handler(DemoError)
async def handle_demo_error(_: Request, exc: DemoError):
    status_code = 500
    # 统一在这里把领域异常翻译成 HTTP 状态码，路由函数本身保持业务语义。
    if isinstance(exc, NotFoundError):
        status_code = 404
    elif isinstance(exc, ConflictError):
        status_code = 409
    elif isinstance(exc, UnsupportedMediaTypeError):
        status_code = 415
    elif isinstance(exc, FileTooLargeError):
        status_code = 413
    elif isinstance(exc, ValidationError):
        status_code = 400
    return JSONResponse(
        status_code=status_code,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    return ok({"status": "up"})


@app.post("/documents/upload")
async def upload_document(
    external_doc_key: str = Form(...),
    title: str = Form(""),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    # demo 仍采用整文件读入，便于把校验、哈希和对象写入串成清晰主路径。
    content = await file.read()
    service = DocumentCommandService(session, build_object_storage())
    outcome = await service.upload_document(
        external_doc_key=external_doc_key,
        title=title,
        file_name=file.filename or "unnamed.txt",
        mime_type=file.content_type or "application/octet-stream",
        content=content,
    )
    payload = UploadResult(
        document_id=outcome.document_id,
        version_id=outcome.version_id,
        reused_existing_version=outcome.reused_existing_version,
        message=outcome.message,
    )
    return ok(payload.model_dump(), message=outcome.message)


@app.get("/documents/{document_id}")
async def get_document(
    document_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    detail = await load_document_detail(session, document_id)
    return ok(detail.model_dump())


@app.get("/versions/{version_id}")
async def get_version(
    version_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    detail = await load_version_detail(session, version_id)
    return ok(detail.model_dump())


@app.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = DocumentCommandService(session, build_object_storage())
    await service.delete_document(document_id)
    return ok(message="删除请求已进入清理流水线")


@app.post("/versions/{version_id}/rebuild")
async def rebuild_version(
    version_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = DocumentCommandService(session, build_object_storage())
    await service.request_rebuild(version_id)
    return ok(message="已写入 REBUILD_REQUESTED")


@app.post("/admin/outbox/dispatch")
async def dispatch_outbox() -> dict[str, Any]:
    await best_effort_dispatch_outbox()
    return ok(message="已触发 Outbox Dispatcher")


@app.post("/ops/outbox/dispatch")
async def dispatch_outbox_ops() -> dict[str, Any]:
    await best_effort_dispatch_outbox()
    return ok(message="已触发 Outbox Dispatcher")


@app.get("/admin/outbox/pending")
@app.get("/ops/outbox/pending")
async def get_pending_outbox(
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    dispatcher = OutboxDispatcherService(session, build_task_queue())
    # 这个接口面向运维观察，不参与主读路径。
    events = await dispatcher.list_pending_events(limit=limit)
    payload = [OutboxEventRead.model_validate(event).model_dump() for event in events]
    return ok(payload)


@app.get("/admin/stats")
async def get_admin_stats(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    outbox_repo = OutboxRepository(session)
    version_repo = VersionRepository(session)
    payload = AdminStatsRead(
        outbox_pending_count=await outbox_repo.count_pending(),
        parse_failed_count=await version_repo.count_by_parse_status(ParseStatus.FAILED),
        index_failed_count=await version_repo.count_by_index_status(IndexStatus.FAILED),
        active_version_count=await version_repo.count_active(),
    )
    return ok(payload.model_dump())


@app.post("/admin/janitor/run")
async def run_janitor() -> dict[str, Any]:
    # 手动触发接口主要用于教学演示和运维排查，不建议当作正常主链路。
    async with session_scope() as session:
        service = JanitorService(session, build_vector_store(), build_search_store())
        result = await service.run_once()
    return ok(result)


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
