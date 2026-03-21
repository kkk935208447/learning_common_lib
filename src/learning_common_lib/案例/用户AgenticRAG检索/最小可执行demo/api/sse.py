"""SSE helpers for task event streaming."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import StreamingResponse

try:
    from ..config import get_settings
    from ..service_runtime import build_runtime_bundle
except ImportError:
    from 最小可执行demo.config import get_settings
    from 最小可执行demo.service_runtime import (
        build_runtime_bundle,
    )


def build_sse_response(request_id: str, request: Request, *, last_event_id: int = 0) -> StreamingResponse:
    settings = get_settings()
    runtime = build_runtime_bundle()
    progress_service = runtime.progress_service
    session_factory = runtime.session_factory

    async def event_iterator():
        async for event in progress_service.stream_sse_events(
            session_factory,
            request_id=request_id,
            last_event_id=last_event_id,
            heartbeat_interval_s=settings.heartbeat_interval_seconds,
        ):
            if await request.is_disconnected():
                break
            yield progress_service.format_sse(event)

    return StreamingResponse(
        event_iterator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
