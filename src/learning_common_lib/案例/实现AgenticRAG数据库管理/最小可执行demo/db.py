"""Database engine and session helpers for API requests and Celery tasks."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

try:
    from .config import get_settings
    from .models import Base
except ImportError:
    from config import get_settings
    from models import Base


_engine = None
_session_factory = None


def build_engine(dsn: str | None = None):
    settings = get_settings()
    return create_async_engine(dsn or settings.mysql_dsn, echo=False, pool_pre_ping=True)


def get_engine():
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def ensure_database_exists() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.mysql_admin_dsn, echo=False, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA "
                    "WHERE SCHEMA_NAME = :schema_name"
                ),
                {"schema_name": settings.mysql_database},
            )
            exists = result.scalar_one_or_none()
            if not exists:
                await conn.execute(
                    text(
                        f"CREATE DATABASE `{settings.mysql_database}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                )
    finally:
        await engine.dispose()


async def create_tables() -> None:
    await ensure_database_exists()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables() -> None:
    settings = get_settings()
    async with get_engine().begin() as conn:
        result = await conn.execute(
            text(
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = :schema_name"
            ),
            {"schema_name": settings.mysql_database},
        )
        existing_tables = {row[0] for row in result.fetchall()}

        # 对教学 demo 来说，显式按依赖逆序删除比 `metadata.drop_all()` 更稳妥：
        # 1. 阅读时更容易看清删除顺序
        # 2. 不会因为 MySQL 反射或 `IF EXISTS` 警告把输出搞得很乱
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in existing_tables:
                await conn.execute(text(f"DROP TABLE `{table.name}`"))


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        await session.close()


@asynccontextmanager
async def task_session_scope() -> AsyncIterator[AsyncSession]:
    # Celery task常常由新的 asyncio event loop 驱动，单独建 engine 可以规避 loop 交叉复用。
    engine = build_engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_db_session(_: Request) -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session
