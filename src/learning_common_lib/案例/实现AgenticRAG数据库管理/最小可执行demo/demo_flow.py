"""Single-process eager smoke test for upload, rebuild, and delete flows."""

from __future__ import annotations

import asyncio
import os
import shutil

# eager 自测会在当前进程内同步执行 Celery 任务，便于快速回归状态机。
os.environ.setdefault("MIN_RAG_CELERY_EAGER", "true")

from sqlalchemy import select

try:
    from .bootstrap import build_object_storage, build_search_store, build_vector_store
    from .config import get_settings
    from .db import create_tables, drop_tables, session_scope
    from .models import OutboxEvent
    from .repositories import DocumentRepository, VersionRepository
    from .services import DocumentCommandService, JanitorService
except ImportError:
    from bootstrap import build_object_storage, build_search_store, build_vector_store
    from config import get_settings
    from db import create_tables, drop_tables, session_scope
    from models import OutboxEvent
    from repositories import DocumentRepository, VersionRepository
    from services import DocumentCommandService, JanitorService


def reset_runtime_dir() -> None:
    # eager 自测会直接读写本地 mock 存储，因此每次都把 runtime 目录清空最直观。
    runtime_dir = get_settings().runtime_dir
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)


async def print_document_state(document_id: int) -> None:
    # 这里打印的是业务态快照，而不是 task 明细，便于对照 README 看状态跃迁。
    async with session_scope() as session:
        doc_repo = DocumentRepository(session)
        version_repo = VersionRepository(session)
        document = await doc_repo.get_by_id(document_id)
        versions = await version_repo.list_by_document(document_id)
        print(
            {
                "document_id": document.id,
                "lifecycle_status": document.lifecycle_status.value,
                "active_version_id": document.active_version_id,
                "latest_version_no": document.latest_version_no,
                "versions": [
                    {
                        "version_id": version.id,
                        "version_no": version.version_no,
                        "parse_status": version.parse_status.value,
                        "index_status": version.index_status.value,
                        "milvus_status": version.milvus_status.value,
                        "es_status": version.es_status.value,
                        "visibility_status": version.visibility_status.value,
                        "chunk_count": version.chunk_count,
                    }
                    for version in versions
                ],
            }
        )


async def print_outbox_state() -> None:
    # 顺手把 Outbox 打印出来，可以验证 eager 模式仍然保留事务消息边界。
    async with session_scope() as session:
        events = list((await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id.asc()))).all())
        print(
            {
                "outbox": [
                    {
                        "id": event.id,
                        "event_type": event.event_type.value,
                        "publish_status": event.publish_status.value,
                        "task_name": event.task_name,
                    }
                    for event in events
                ]
            }
        )


async def main() -> None:
    reset_runtime_dir()
    # 这个脚本本身就是“自包含回归”，因此会主动 reset 数据库和 runtime 目录。
    await drop_tables()
    await create_tables()
    print("=== 初始化完成，开始执行 eager 模式全链路 ===")

    async with session_scope() as session:
        service = DocumentCommandService(session, build_object_storage())
        outcome = await service.upload_document(
            external_doc_key="employee-handbook",
            title="员工手册",
            file_name="employee.txt",
            mime_type="text/plain",
            content=(
                "第一章：请假流程。\n"
                "员工请假需要提前在系统中提交申请。\n"
                "第二章：报销流程。\n"
                "所有报销单据需在月底前提交。\n"
                "第三章：考勤规范。\n"
                "上班时间为上午九点。\n"
            ).encode("utf-8"),
        )
        print(
            {
                "document_id": outcome.document_id,
                "version_id": outcome.version_id,
                "message": outcome.message,
                "reused_existing_version": outcome.reused_existing_version,
            }
        )

    await print_outbox_state()
    await print_document_state(outcome.document_id)

    vector_store = build_vector_store()
    search_store = build_search_store()
    # 人为删掉一个向量投影，模拟 Janitor 发现“事实表与投影 count 不一致”的场景。
    removed = await vector_store.remove_one_for_version(outcome.version_id)
    print({"tamper_vector_store": removed})

    async with session_scope() as session:
        janitor = JanitorService(session, vector_store, search_store)
        result = await janitor.run_once()
        print({"janitor_result": result})

    await print_outbox_state()
    await print_document_state(outcome.document_id)

    async with session_scope() as session:
        service = DocumentCommandService(session, build_object_storage())
        await service.delete_document(outcome.document_id)

    await print_outbox_state()
    await print_document_state(outcome.document_id)
    print("=== demo 完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
