"""Offline submit demo that uses the service layer while worker/beat are running."""

from __future__ import annotations

import asyncio

try:
    from .domain.contracts import SearchSubmitRequest
    from .service_runtime import build_runtime_bundle, build_search_command_service
except ImportError:
    import sys
    from pathlib import Path

    demo_parent = Path(__file__).resolve().parent.parent
    if str(demo_parent) not in sys.path:
        sys.path.insert(0, str(demo_parent))
    from 最小可执行demo.domain.contracts import (
        SearchSubmitRequest,
    )
    from 最小可执行demo.service_runtime import (
        build_runtime_bundle,
        build_search_command_service,
    )


async def main() -> None:
    service = build_search_command_service(use_task_engine=True)
    runtime = build_runtime_bundle(use_task_engine=True)
    accepted = await service.submit_search(
        SearchSubmitRequest(
            session_id="sess_offline_demo_001",
            query="请帮我整理公司近 90 天差旅报销规则的变化",
            kb_code="default",
            scope_json=None,
        )
    )
    print("submit:", accepted.model_dump(mode="json"))

    final_snapshot = None
    for idx in range(60):
        async with runtime.session_factory() as session:
            final_snapshot = await runtime.progress_service.build_snapshot(session, accepted.request_id)
        print("poll:", idx, final_snapshot.status, final_snapshot.active_plan_version)
        if final_snapshot.status in {"COMPLETED", "DEGRADED", "FAILED", "WAITING_CLARIFICATION"}:
            break
        await asyncio.sleep(1)

    if final_snapshot is not None:
        print("final:", final_snapshot.model_dump(mode="json"))


if __name__ == "__main__":
    asyncio.run(main())
