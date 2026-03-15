from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from .bootstrap import build_object_storage, build_search_store, build_vector_store
    from .config import get_settings
    from .db import create_tables, dispose_engine, get_db_session, session_scope
    from .errors import ConflictError, DemoError, NotFoundError, ValidationError
    from .repositories import DocumentRepository, VersionRepository
    from .schemas import DocumentRead, UploadResult, VersionRead
    from .services import DocumentCommandService, JanitorService, best_effort_dispatch_outbox
except ImportError:
    from bootstrap import build_object_storage, build_search_store, build_vector_store
    from config import get_settings
    from db import create_tables, dispose_engine, get_db_session, session_scope
    from errors import ConflictError, DemoError, NotFoundError, ValidationError
    from repositories import DocumentRepository, VersionRepository
    from schemas import DocumentRead, UploadResult, VersionRead
    from services import DocumentCommandService, JanitorService, best_effort_dispatch_outbox


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    await create_tables()
    try:
        yield
    finally:
        await dispose_engine()


app = FastAPI(title="Agentic RAG Min Demo", lifespan=lifespan)


@app.exception_handler(DemoError)
async def handle_demo_error(_: Request, exc: DemoError):
    status_code = 500
    if isinstance(exc, NotFoundError):
        status_code = 404
    elif isinstance(exc, ConflictError):
        status_code = 409
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


@app.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = DocumentCommandService(session, build_object_storage())
    await service.delete_document(document_id)
    return ok(message="删除请求已进入清理流水线")


@app.post("/admin/outbox/dispatch")
async def dispatch_outbox() -> dict[str, Any]:
    await best_effort_dispatch_outbox()
    return ok(message="已触发 Outbox Dispatcher")


@app.post("/admin/janitor/run")
async def run_janitor() -> dict[str, Any]:
    async with session_scope() as session:
        service = JanitorService(session, build_vector_store(), build_search_store())
        result = await service.run_once()
    return ok(result)


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
