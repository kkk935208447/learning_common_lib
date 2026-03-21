"""FastAPI routes for the deepsearch minimum demo."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Request

try:
    from ..domain.contracts import ClarificationAnswerRequest, SearchSubmitRequest
    from ..service_runtime import build_search_command_service
    from .sse import build_sse_response
except ImportError:
    from 最小可执行demo.domain.contracts import (
        ClarificationAnswerRequest,
        SearchSubmitRequest,
    )
    from 最小可执行demo.service_runtime import (
        build_search_command_service,
    )
    from 最小可执行demo.api.sse import (
        build_sse_response,
    )


router = APIRouter(prefix="/api/v1")


def ok(data: Any = None, message: str = "success") -> dict[str, Any]:
    return {"code": "OK", "message": message, "data": data}


@router.get("/health")
async def health() -> dict[str, Any]:
    return ok({"status": "up"})


@router.post("/search")
async def submit_search(payload: SearchSubmitRequest) -> dict[str, Any]:
    service = build_search_command_service()
    accepted = await service.submit_search(payload)
    return ok(accepted.model_dump(mode="json"))


@router.get("/search/{request_id}")
async def get_snapshot(request_id: str) -> dict[str, Any]:
    service = build_search_command_service()
    snapshot = await service.get_snapshot(request_id)
    return ok(snapshot.model_dump(mode="json"))


@router.get("/search/{request_id}/events")
async def stream_events(
    request_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    service = build_search_command_service()
    await service.get_snapshot(request_id)
    parsed_last_id = int(last_event_id or 0)
    return build_sse_response(request_id, request, last_event_id=parsed_last_id)


@router.post("/search/{request_id}/clarification")
async def submit_clarification(request_id: str, payload: ClarificationAnswerRequest) -> dict[str, Any]:
    service = build_search_command_service()
    snapshot = await service.submit_clarification(request_id, payload.selected_option_id)
    return ok(snapshot.model_dump(mode="json"))
