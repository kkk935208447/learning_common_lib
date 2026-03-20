"""FastAPI entrypoint for the deepsearch minimum demo."""

from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

try:
    from .api.routes import router
    from .config import get_settings
    from .db import create_tables, dispose_engine
    from .errors import ConflictError, DemoError, NotFoundError, ValidationError
except ImportError:
    import sys
    from pathlib import Path

    demo_parent = Path(__file__).resolve().parent.parent
    if str(demo_parent) not in sys.path:
        sys.path.insert(0, str(demo_parent))
    from 最小可执行demo.api.routes import router
    from 最小可执行demo.config import get_settings
    from 最小可执行demo.db import create_tables, dispose_engine
    from 最小可执行demo.errors import (
        ConflictError,
        DemoError,
        NotFoundError,
        ValidationError,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_settings().auto_create_tables_on_startup:
        await create_tables()
    try:
        yield
    finally:
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
    return JSONResponse(status_code=status_code, content={"code": exc.code, "message": exc.message, "data": None})


@app.exception_handler(ValueError)
async def handle_value_error(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"code": "VALUE_ERROR", "message": str(exc), "data": None})


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
