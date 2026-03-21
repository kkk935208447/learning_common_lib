"""Seed the upstream knowledge-base demo with a small set of active documents."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("MIN_RAG_CELERY_EAGER", "1")

try:
    from ...实现AgenticRAG数据库管理.最小可执行demo.bootstrap import build_object_storage
    from ...实现AgenticRAG数据库管理.最小可执行demo.db import create_tables as create_upstream_tables
    from ...实现AgenticRAG数据库管理.最小可执行demo.db import session_scope as upstream_session_scope
    from ...实现AgenticRAG数据库管理.最小可执行demo.services.document_command import DocumentCommandService
except ImportError:
    cases_root = Path(__file__).resolve().parent.parent.parent.parent.parent
    if str(cases_root) not in sys.path:
        sys.path.insert(0, str(cases_root))
    from 实现AgenticRAG数据库管理.最小可执行demo.bootstrap import build_object_storage
    from 实现AgenticRAG数据库管理.最小可执行demo.db import (
        create_tables as create_upstream_tables,
    )
    from 实现AgenticRAG数据库管理.最小可执行demo.db import (
        session_scope as upstream_session_scope,
    )
    from 实现AgenticRAG数据库管理.最小可执行demo.services.document_command import (
        DocumentCommandService,
    )


SAMPLE_DOCS = [
    (
        "travel_policy_v1",
        "差旅报销制度",
        """差旅报销制度（当前活动版）

一、交通标准
1. 市内交通凭发票报销。
2. 高铁默认二等座，特殊情况需审批。

二、住宿标准
1. 一线城市单晚标准 500 元。
2. 其他城市单晚标准 350 元。

三、票据要求
1. 发票抬头必须为公司全称。
2. 电子票据允许入账。

四、近 90 天变化
1. 一线城市住宿标准由 450 元调整为 500 元。
2. 高铁商务座必须由总监审批。
""",
    ),
    (
        "travel_policy_compare",
        "差旅补充说明",
        """差旅补充说明

一、最近制度变化摘要
1. 对比上一版，住宿标准有所上调。
2. 对高铁商务座增加了审批要求。

二、报销材料
1. 酒店发票和行程单缺一不可。
2. 如无纸质行程单，可使用电子行程证明。

三、例外规则
1. 海外差旅不适用国内住宿上限。
2. 因会议协议价产生的住宿可按协议价执行。
""",
    ),
]


async def seed_demo_kb() -> None:
    await create_upstream_tables()
    async with upstream_session_scope() as session:
        service = DocumentCommandService(session, build_object_storage())
        for external_doc_key, title, content in SAMPLE_DOCS:
            await service.upload_document(
                external_doc_key=external_doc_key,
                title=title,
                file_name=f"{external_doc_key}.txt",
                mime_type="text/plain",
                content=content.encode("utf-8"),
            )


def main() -> None:
    asyncio.run(seed_demo_kb())


if __name__ == "__main__":
    main()
