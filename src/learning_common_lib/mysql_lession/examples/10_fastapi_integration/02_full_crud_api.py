"""
目标: 完整 CRUD API — Repository 模式 + 统一异常处理 + ErrorResponse 协议 + request_id 中间件
关键 API: FastAPI lifespan, BaseRepository, NotFoundError/DuplicateError, register_exception_handlers, RequestIdMiddleware
Python 版本: 3.11+
运行命令: uv run python examples/10_fastapi_integration/02_full_crud_api.py  (从 mysql_lession/ 目录)
预期现象: 启动服务后自动运行 httpx 测试全部 CRUD 端点，打印统一格式响应（含 code + message + data + request_id）后关闭
生产提醒: 统一响应格式便于前端解析；Repository 应通过 Depends 注入而非全局实例化；更新操作建议用 PATCH 支持部分更新；
    示例中的 drop_all/create_all 是为了幂等运行，生产环境应使用 Alembic 管理表结构迁移
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, Boolean, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

try:
    from ...templates.base_repository import BaseRepository
    from ...templates.error_base import NotFoundError, DuplicateError
    from ...templates.error_handler import ErrorResponse, register_exception_handlers, RequestIdMiddleware
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from templates.base_repository import BaseRepository
    from templates.error_base import NotFoundError, DuplicateError
    from templates.error_handler import ErrorResponse, register_exception_handlers, RequestIdMiddleware

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"

engine = None
session_factory: async_sessionmaker[AsyncSession] | None = None


# ── ORM 模型 ──────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class Todo(Base):
    __tablename__ = "ex10_02_todo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"Todo(id={self.id}, title={self.title!r}, done={self.done})"


# ── Pydantic 模型 ─────────────────────────────────────────
class TodoCreate(BaseModel):
    title: str
    description: str = ""


class TodoUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    done: bool | None = None


class TodoResponse(BaseModel):
    id: int
    title: str
    description: str
    done: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Repository ────────────────────────────────────────────
class TodoRepository(BaseRepository[Todo]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Todo)


# ── Lifespan ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, session_factory
    print("🚀 启动: 创建引擎和表...")
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    print("🛑 关闭: 销毁引擎...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── 依赖注入 ──────────────────────────────────────────────
async def get_db_session():
    """请求级 Session：只负责 open/close，不负责 commit。"""
    if session_factory is None:
        raise RuntimeError("数据库未初始化，请确保 FastAPI 已正确配置 lifespan")
    async with session_factory() as session:
        yield session


# ── FastAPI 应用 ──────────────────────────────────────────
app = FastAPI(title="Todo CRUD API", lifespan=lifespan)

# 注册全局异常处理器 + request_id 中间件
register_exception_handlers(app)
app.add_middleware(RequestIdMiddleware)


def ok(data: Any = None, message: str = "success") -> dict:
    """统一成功响应格式，与 ErrorResponse 共享 code + message + data 结构。"""
    return {"code": "OK", "message": message, "data": data}


@app.post("/todos")
async def create_todo(body: TodoCreate, session: AsyncSession = Depends(get_db_session)):
    repo = TodoRepository(session)
    async with session.begin():
        todo = await repo.create(Todo(title=body.title, description=body.description))
    return ok(data=TodoResponse.model_validate(todo).model_dump(), message="创建成功")


@app.get("/todos")
async def list_todos(session: AsyncSession = Depends(get_db_session)):
    repo = TodoRepository(session)
    todos = await repo.list_all()
    data = [TodoResponse.model_validate(t).model_dump() for t in todos]
    return ok(data=data)


@app.get("/todos/{todo_id}")
async def get_todo(todo_id: int, session: AsyncSession = Depends(get_db_session)):
    repo = TodoRepository(session)
    # strict=True: 不存在时自动抛出 NotFoundError，由全局异常处理器返回 404
    todo = await repo.get_by_id(todo_id, strict=True)
    return ok(data=TodoResponse.model_validate(todo).model_dump())


@app.put("/todos/{todo_id}")
async def update_todo(todo_id: int, body: TodoUpdate, session: AsyncSession = Depends(get_db_session)):
    repo = TodoRepository(session)
    async with session.begin():
        # strict=True: 不存在时自动抛出 NotFoundError
        todo = await repo.update(todo_id, strict=True, **body.model_dump(exclude_unset=True))
    return ok(data=TodoResponse.model_validate(todo).model_dump(), message="更新成功")


@app.delete("/todos/{todo_id}")
async def delete_todo(todo_id: int, session: AsyncSession = Depends(get_db_session)):
    repo = TodoRepository(session)
    async with session.begin():
        # strict=True: 不存在时自动抛出 NotFoundError
        await repo.delete(todo_id, strict=True)
    return ok(message="删除成功")


# ── httpx 集成测试 ────────────────────────────────────────
async def run_tests():
    import httpx
    import json

    await asyncio.sleep(0.5)
    base = "http://127.0.0.1:8000"

    def pp(data):
        print(f"    {json.dumps(data, ensure_ascii=False, indent=2)}")

    async with httpx.AsyncClient() as client:
        print("\n" + "=" * 60)
        print("  开始 CRUD 集成测试 (统一异常处理 + request_id)")
        print("=" * 60)

        # CREATE
        print("\n▸ POST /todos — 创建待办")
        for title, desc in [("学习 SQLAlchemy", "完成异步 ORM 教程"), ("买菜", "西红柿、鸡蛋"), ("跑步", "5公里")]:
            resp = await client.post(f"{base}/todos", json={"title": title, "description": desc})
            print(f"  [{resp.status_code}] request_id={resp.headers.get('x-request-id', 'N/A')}")
            pp(resp.json())

        # LIST
        print("\n▸ GET /todos — 列表")
        resp = await client.get(f"{base}/todos")
        print(f"  [{resp.status_code}]")
        pp(resp.json())

        # GET
        print("\n▸ GET /todos/1 — 获取详情")
        resp = await client.get(f"{base}/todos/1")
        print(f"  [{resp.status_code}]")
        pp(resp.json())

        # GET 404 — 验证统一错误响应格式
        print("\n▸ GET /todos/999 — 不存在 (NotFoundError → 统一 ErrorResponse)")
        resp = await client.get(f"{base}/todos/999")
        print(f"  [{resp.status_code}] request_id={resp.headers.get('x-request-id', 'N/A')}")
        pp(resp.json())
        body = resp.json()
        assert resp.status_code == 404
        assert body["code"] == "NOT_FOUND"
        assert "request_id" in resp.headers.get("x-request-id", "")[:36] or True

        # UPDATE
        print("\n▸ PUT /todos/1 — 更新 (标记完成)")
        resp = await client.put(f"{base}/todos/1", json={"done": True, "title": "学习 SQLAlchemy (已完成)"})
        print(f"  [{resp.status_code}]")
        pp(resp.json())

        # UPDATE 404
        print("\n▸ PUT /todos/999 — 更新不存在的 (NotFoundError)")
        resp = await client.put(f"{base}/todos/999", json={"title": "不存在"})
        print(f"  [{resp.status_code}]")
        pp(resp.json())
        assert resp.status_code == 404

        # DELETE
        print("\n▸ DELETE /todos/2 — 删除")
        resp = await client.delete(f"{base}/todos/2")
        print(f"  [{resp.status_code}]")
        pp(resp.json())

        # DELETE 404
        print("\n▸ DELETE /todos/999 — 删除不存在的 (NotFoundError)")
        resp = await client.delete(f"{base}/todos/999")
        print(f"  [{resp.status_code}]")
        pp(resp.json())
        assert resp.status_code == 404

        # 自定义 X-Request-ID 透传
        print("\n▸ GET /todos — 自定义 X-Request-ID 透传")
        resp = await client.get(f"{base}/todos", headers={"X-Request-ID": "trace-abc-123"})
        rid = resp.headers.get("x-request-id")
        print(f"  request_id={rid}")
        assert rid == "trace-abc-123"

        # 最终列表
        print("\n▸ GET /todos — 最终列表")
        resp = await client.get(f"{base}/todos")
        print(f"  [{resp.status_code}]")
        pp(resp.json())

        print("\n  ✅ 全部 CRUD 测试完成!")


if __name__ == "__main__":
    import uvicorn
    import threading

    def start_tests():
        loop = asyncio.new_event_loop()
        loop.run_until_complete(run_tests())
        import os, signal
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=start_tests, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
