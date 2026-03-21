"""Shared setup helpers for test fixtures and control-plane initialization."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path


demo_parent = Path(__file__).resolve().parents[3].parent
if str(demo_parent) not in sys.path:
    sys.path.insert(0, str(demo_parent))

try:
    from ....实现AgenticRAG数据库管理.最小可执行demo.bootstrap import build_object_storage
    from ....实现AgenticRAG数据库管理.最小可执行demo.db import create_tables as create_upstream_tables
    from ....实现AgenticRAG数据库管理.最小可执行demo.db import session_scope as upstream_session_scope
    from ....实现AgenticRAG数据库管理.最小可执行demo.init_db import main as upstream_init_main
    from ....实现AgenticRAG数据库管理.最小可执行demo.services.document_command import DocumentCommandService
    from ...infrastructure.database import create_tables as create_control_tables, get_engine
    from ...infrastructure.models import Base
    from ...infrastructure.settings import get_settings
except ImportError:
    from 实现AgenticRAG数据库管理.最小可执行demo.bootstrap import build_object_storage
    from 实现AgenticRAG数据库管理.最小可执行demo.db import create_tables as create_upstream_tables
    from 实现AgenticRAG数据库管理.最小可执行demo.db import session_scope as upstream_session_scope
    from 实现AgenticRAG数据库管理.最小可执行demo.init_db import main as upstream_init_main
    from 实现AgenticRAG数据库管理.最小可执行demo.services.document_command import DocumentCommandService
    from 最小可执行demo.infrastructure.database import create_tables as create_control_tables, get_engine
    from 最小可执行demo.infrastructure.models import Base
    from 最小可执行demo.infrastructure.settings import get_settings


logger = logging.getLogger(__name__)


def load_knowledge_manifest() -> tuple[Path, list[dict]]:
    settings = get_settings()
    root = settings.test_fixtures_dir / "knowledge"
    manifest_path = root / "default_documents.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return root, list(payload.get("documents") or [])


async def prepare_upstream_from_fixtures() -> dict[str, int]:
    await upstream_init_main()
    await create_upstream_tables()
    root, documents = load_knowledge_manifest()
    logger.info("preparing upstream fixtures documents=%s root=%s", len(documents), root)
    async with upstream_session_scope() as session:
        service = DocumentCommandService(session, build_object_storage())
        for item in documents:
            file_name = str(item["file_name"])
            content = (root / file_name).read_bytes()
            await service.upload_document(
                external_doc_key=str(item["external_doc_key"]),
                title=str(item["title"]),
                file_name=file_name,
                mime_type=str(item.get("mime_type") or "text/plain"),
                content=content,
            )
    return {"documents": len(documents)}


async def prepare_control_plane() -> dict[str, str]:
    await create_control_tables()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    logger.info("control plane tables recreated")
    return {"status": "ok"}


def run_async(coro):
    return asyncio.run(coro)
