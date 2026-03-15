from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class VersionRead(BaseModel):
    id: int
    version_no: int
    file_hash: str
    file_name: str
    file_size: int
    mime_type: str
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

    model_config = {"from_attributes": True}


class DocumentRead(BaseModel):
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
    document_id: int
    version_id: int
    reused_existing_version: bool
    message: str


class OkResponse(BaseModel):
    code: str = "OK"
    message: str = "success"
    data: dict | list | None = None
