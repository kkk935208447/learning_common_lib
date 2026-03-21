"""Session and clarification persistence helpers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.contracts import ClarificationRequest
from ..errors import ConflictError, ValidationError
from .common import json_safe, normalize_utc_datetime, utcnow

try:
    from ..infrastructure.models import Session, SessionTurn
except ImportError:
    from 最小可执行demo.infrastructure.models import Session, SessionTurn


class SessionService:
    def get_clarification_deadline(self, turn: SessionTurn) -> datetime | None:
        if turn.expires_at is None:
            return None
        return normalize_utc_datetime(turn.expires_at)

    def is_clarification_expired(self, turn: SessionTurn) -> bool:
        deadline = self.get_clarification_deadline(turn)
        return deadline is not None and deadline <= utcnow()

    async def ensure_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        tenant_id: str,
        user_id: str,
        initial_query: str | None = None,
    ) -> Session:
        item = await session.scalar(select(Session).where(Session.session_id == session_id))
        if item is not None:
            return item
        item = Session(
            session_id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
            topic=(initial_query or "")[:256],
            mentioned_entities_json={},
            rolling_summary="",
            status="ACTIVE",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(item)
        await session.flush()
        return item

    async def append_query_turn(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        task_id: int,
        query: str,
    ) -> SessionTurn:
        turn = SessionTurn(
            session_id=session_id,
            task_id=task_id,
            role="USER",
            turn_type="QUERY",
            content=query,
            created_at=utcnow(),
        )
        session.add(turn)
        await session.flush()
        return turn

    async def record_clarification_request(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        task_id: int,
        clarification: ClarificationRequest,
    ) -> SessionTurn:
        turn = SessionTurn(
            session_id=session_id,
            task_id=task_id,
            role="SYSTEM",
            turn_type="CLARIFY_REQUEST",
            content=clarification.question,
            clarification_source=clarification.clarification_source,
            question_type=clarification.question_type,
            options_json=json_safe([option.model_dump(mode="json") for option in clarification.options]),
            default_option_id=clarification.default_option_id,
            expires_at=clarification.expires_at,
            created_at=utcnow(),
        )
        session.add(turn)
        await session.flush()
        return turn

    async def record_clarification_reply(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        task_id: int,
        selected_option_id: str,
        answer_origin: str,
    ) -> SessionTurn:
        turn = SessionTurn(
            session_id=session_id,
            task_id=task_id,
            role="USER" if answer_origin == "USER" else "SYSTEM",
            turn_type="CLARIFY_REPLY",
            content=selected_option_id,
            selected_option_id=selected_option_id,
            answer_origin=answer_origin,
            created_at=utcnow(),
        )
        session.add(turn)
        await session.flush()
        return turn

    async def get_latest_clarification_request(
        self,
        session: AsyncSession,
        *,
        task_id: int,
    ) -> SessionTurn | None:
        stmt = (
            select(SessionTurn)
            .where(SessionTurn.task_id == task_id)
            .where(SessionTurn.turn_type == "CLARIFY_REQUEST")
            .order_by(SessionTurn.id.desc())
            .limit(1)
        )
        return await session.scalar(stmt)

    async def validate_clarification_answer(
        self,
        session: AsyncSession,
        *,
        task_id: int,
        selected_option_id: str,
    ) -> SessionTurn:
        latest_request = await self.get_latest_clarification_request(session, task_id=task_id)
        if latest_request is None:
            raise ConflictError("当前任务没有待处理的澄清请求")
        options = latest_request.options_json or []
        valid_ids = {option["id"] for option in options}
        if selected_option_id not in valid_ids:
            raise ValidationError("selected_option_id 非法")
        return latest_request

    async def append_answer_turn(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        task_id: int,
        answer: str,
        citations: list[str],
        coverage_summary: dict,
    ) -> SessionTurn:
        turn = SessionTurn(
            session_id=session_id,
            task_id=task_id,
            role="ASSISTANT",
            turn_type="ANSWER",
            content=answer,
            summary_json={"citations": citations, "coverage_summary": coverage_summary},
            created_at=utcnow(),
        )
        session.add(turn)
        session_item = await session.scalar(select(Session).where(Session.session_id == session_id))
        if session_item is not None:
            previous_summary = session_item.rolling_summary or ""
            session_item.rolling_summary = f"{previous_summary}\nQ/A: {answer[:240]}".strip()[:4000]
            session_item.updated_at = utcnow()
        await session.flush()
        return turn
