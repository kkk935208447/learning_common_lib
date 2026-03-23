"""Single-process eager demo flow for the deepsearch minimum demo."""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DEEPSEARCH_DEMO_CELERY_EAGER", "1")
os.environ.setdefault("MIN_RAG_CELERY_EAGER", "1")

try:
    from ...domain.contracts import SearchSubmitRequest
    from ...infrastructure.runtime_bundle import build_search_command_service
    from ..setup.support import prepare_demo_environment
except ImportError:
    import sys
    from pathlib import Path

    package_parent = Path(__file__).resolve().parents[3]
    if str(package_parent) not in sys.path:
        sys.path.insert(0, str(package_parent))
    from 最小可执行demo.domain.contracts import SearchSubmitRequest
    from 最小可执行demo.infrastructure.runtime_bundle import (
        build_search_command_service,
    )
    from 最小可执行demo.scripts.setup.support import prepare_demo_environment


async def main() -> None:
    # demo_flow 直接复用正式服务层，不再手工创建任务、写 turn 和拼装澄清状态。
    await prepare_demo_environment()
    service = build_search_command_service(use_task_engine=True)
    accepted = await service.submit_search(
        SearchSubmitRequest(
            session_id="sess_demo_001",
            query="请帮我整理公司近 90 天差旅报销规则的变化",
            kb_code="default",
            scope_json=None,
        )
    )

    print(
        "submit:",
        accepted.model_dump(mode="json"),
    )

    request_id = accepted.request_id
    final_snapshot = None
    for idx in range(60):
        snapshot = await service.get_snapshot(request_id)
        print("poll:", idx, snapshot.status, snapshot.active_plan_version)
        if snapshot.status == "WAITING_CLARIFICATION" and snapshot.clarification_request is not None:
            snapshot = await service.submit_clarification(
                request_id,
                snapshot.clarification_request.default_option_id,
            )
            print("clarification:", snapshot.model_dump(mode="json"))
        final_snapshot = snapshot
        if snapshot.status in {"COMPLETED", "DEGRADED", "FAILED"}:
            break
        await asyncio.sleep(1)
    if final_snapshot is None:
        final_snapshot = await service.get_snapshot(request_id)
    print("final:", final_snapshot.model_dump(mode="json"))


if __name__ == "__main__":
    asyncio.run(main())
