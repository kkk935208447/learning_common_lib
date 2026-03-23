"""Shared setup helpers for demo scripts and test runners."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any


try:
    from ...实现AgenticRAG数据库管理.最小可执行demo.bootstrap import build_object_storage
    from ...实现AgenticRAG数据库管理.最小可执行demo.db import (
        create_tables as create_upstream_tables,
    )
    from ...实现AgenticRAG数据库管理.最小可执行demo.db import (
        session_scope as upstream_session_scope,
    )
    from ...实现AgenticRAG数据库管理.最小可执行demo.init_db import (
        main as upstream_init_main,
    )
    from ...实现AgenticRAG数据库管理.最小可执行demo.services.document_command import (
        DocumentCommandService,
    )
    from ...infrastructure.database import create_tables as create_control_tables, get_engine
    from ...infrastructure.models import Base
    from ...infrastructure.settings import get_settings
except ImportError:
    package_parent = Path(__file__).resolve().parents[3]
    cases_root = Path(__file__).resolve().parents[4]
    for path in (package_parent, cases_root):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from 实现AgenticRAG数据库管理.最小可执行demo.bootstrap import build_object_storage
    from 实现AgenticRAG数据库管理.最小可执行demo.db import (
        create_tables as create_upstream_tables,
    )
    from 实现AgenticRAG数据库管理.最小可执行demo.db import (
        session_scope as upstream_session_scope,
    )
    from 实现AgenticRAG数据库管理.最小可执行demo.init_db import (
        main as upstream_init_main,
    )
    from 实现AgenticRAG数据库管理.最小可执行demo.services.document_command import (
        DocumentCommandService,
    )
    from 最小可执行demo.infrastructure.database import create_tables as create_control_tables, get_engine
    from 最小可执行demo.infrastructure.models import Base
    from 最小可执行demo.infrastructure.settings import get_settings


def load_knowledge_manifest(
    manifest_path: Path | None = None,
) -> tuple[Path, list[dict[str, Any]]]:
    settings = get_settings()
    # 所有 demo / test 的上游知识准备统一从 fixtures manifest 读取，
    # 避免脚本层和测试层各维护一份样例文档正文。
    resolved_path = manifest_path or (
        settings.test_fixtures_dir / "knowledge" / "default_documents.json"
    )
    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    return resolved_path.parent, list(payload.get("documents") or [])


async def seed_upstream_kb(
    *,
    reset_upstream: bool = False,
    manifest_path: Path | None = None,
) -> dict[str, int]:
    if reset_upstream:
        await upstream_init_main()
    else:
        await create_upstream_tables()
    root, documents = load_knowledge_manifest(manifest_path)
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


async def reset_control_plane() -> dict[str, str]:
    # 这里保留 drop + create 语义，作为当前 demo 的唯一控制面重置入口。
    await create_control_tables()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return {"status": "ok"}


async def prepare_demo_environment(
    *,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    # 统一的高层准备入口：先重建上游知识，再重置当前控制面。
    # test runner、production_stack_suite、demo_flow 都应该复用这里，
    # 避免初始化顺序和数据源分叉。
    upstream = await seed_upstream_kb(
        reset_upstream=True,
        manifest_path=manifest_path,
    )
    control_plane = await reset_control_plane()
    return {
        "upstream": upstream,
        "control_plane": control_plane,
    }


def run_async(coro):
    return asyncio.run(coro)
