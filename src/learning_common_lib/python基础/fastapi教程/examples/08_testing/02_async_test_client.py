"""
目标: 演示 httpx AsyncClient 异步测试 FastAPI 应用
关键 API: APIRouter, httpx.AsyncClient, httpx.ASGITransport, dependency_overrides
Python 版本: 3.11+
运行命令: uv run python examples/08_testing/02_async_test_client.py  (手动探索 /docs)
测试命令: uv run python examples/08_testing/02_async_test_client_test.py
生产提醒: 异步测试适合测试 WebSocket、SSE、依赖中有 async 操作的端点
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

_db: dict[int, dict] = {}
_next_id = 0


async def get_db() -> dict:
    """模拟异步数据库依赖。"""
    return _db


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["testing"])


@router.post("/notes", status_code=status.HTTP_201_CREATED)
async def create_note(title: str, db: dict = Depends(get_db)):
    global _next_id
    _next_id += 1
    note = {"id": _next_id, "title": title}
    db[_next_id] = note
    return JSONResponse(content=note, status_code=status.HTTP_201_CREATED)


@router.get("/notes")
async def list_notes(db: dict = Depends(get_db)):
    return JSONResponse(content=list(db.values()))


@router.get("/notes/{note_id}")
async def get_note(note_id: int, db: dict = Depends(get_db)):
    if note_id not in db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Note not found"
        )
    return JSONResponse(content=db[note_id])


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="02_async_test_client — 异步测试")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
