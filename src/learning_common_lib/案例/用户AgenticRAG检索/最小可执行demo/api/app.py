"""FastAPI application entrypoint for the deepsearch minimum demo."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

try:
    from ..application.errors import ConflictError, DemoError, NotFoundError, ValidationError
    from ..infrastructure.database import dispose_engine
    from ..infrastructure.settings import get_settings
    from ..infrastructure.runtime_bundle import close_runtime_resources
    from .routes import router
except ImportError:
    import sys
    from pathlib import Path

    package_parent = Path(__file__).resolve().parents[2]
    if str(package_parent) not in sys.path:
        sys.path.insert(0, str(package_parent))
    from 最小可执行demo.api.routes import router
    from 最小可执行demo.application.errors import (
        ConflictError,
        DemoError,
        NotFoundError,
        ValidationError,
    )
    from 最小可执行demo.infrastructure.database import dispose_engine
    from 最小可执行demo.infrastructure.settings import get_settings
    from 最小可执行demo.infrastructure.runtime_bundle import close_runtime_resources


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        logger.info("deepsearch api starting")
        yield
    finally:
        logger.info("deepsearch api shutting down")
        await close_runtime_resources()
        await dispose_engine()


app = FastAPI(title="AgenticRAG DeepSearch Min Demo", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(DemoError)
async def handle_deepsearch_error(_: Request, exc: DemoError):
    status_code = 500
    if isinstance(exc, NotFoundError):
        status_code = 404
    elif isinstance(exc, ConflictError):
        status_code = 409
    elif isinstance(exc, ValidationError):
        status_code = 400
    logger.warning("api handled DemoError code=%s message=%s status=%s", exc.code, exc.message, status_code)
    return JSONResponse(
        status_code=status_code,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.exception_handler(ValueError)
async def handle_value_error(_: Request, exc: ValueError):
    logger.warning("api handled ValueError message=%s", exc)
    return JSONResponse(
        status_code=400,
        content={"code": "VALUE_ERROR", "message": str(exc), "data": None},
    )


def main() -> None:
    settings = get_settings()
    logger.info("starting uvicorn host=%s port=%s", settings.api_host, settings.api_port)
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
