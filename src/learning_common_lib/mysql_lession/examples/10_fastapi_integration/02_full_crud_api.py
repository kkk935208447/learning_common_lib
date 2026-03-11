"""
目标: 完整 CRUD API — Repository 模式 + 统一响应格式 + 错误处理
关键 API: FastAPI lifespan, BaseRepository, Pydantic response_model, HTTPException
Python 版本: 3.11+
运行命令: uv run python examples/10_fastapi_integration/02_full_crud_api.py  (从 mysql_lession/ 目录)
预期现象: 启动服务后自动运行 httpx 测试全部 CRUD 端点，打印统一格式响应后关闭
生产提醒: 统一响应格式便于前端解析；Repository 应通过 Depends 注入而非全局实例化；更新操作建议用 PATCH 支持部分更新；
    示例中的 drop_all/create_all 是为了幂等运行，生产环境应使用 Alembic 管理表结构迁移
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Generic, Sequence, TypeVar

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, Boolean, select, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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


class UnifiedResponse(BaseModel):
    """统一响应格式"""
    code: int = 0
    message: str = "ok"
    data: Any = None


# ── 泛型 Repository ──────────────────────────────────────
T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    def __init__(self, session: AsyncSession, model_cls: type[T]) -> None:
        self._session = session
        self._model_cls = model_cls

    async def get_by_id(self, id_: int) -> T | None:
        return await self._session.get(self._model_cls, id_)

    async def list_all(self) -> Sequence[T]:
        result = await self._session.execute(select(self._model_cls))
        return result.scalars().all()

    async def create(self, **kwargs) -> T:
        instance = self._model_cls(**kwargs)
        self._session.add(instance)
        # Repository 只 flush，不 commit。
        # 这样它可以被多个业务步骤组合进同一个事务，而不会在中途偷偷提交。
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def update(self, id_: int, **kwargs) -> T | None:
        instance = await self.get_by_id(id_)
        if instance is None:
            return None
        for k, v in kwargs.items():
            if v is not None:
                setattr(instance, k, v)
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def delete(self, id_: int) -> bool:
        instance = await self.get_by_id(id_)
        if instance is None:
            return False
        await self._session.delete(instance)
        await self._session.flush()
        return True


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
    """
    请求级 Session：这里只负责 open/close，不负责 commit。

    教学上要把两个概念分开：
    1. Session 生命周期：一个请求拿一个 Session，用完关闭；
    2. 事务生命周期：只在写操作那一小段代码里显式 begin/commit。
    """
    if session_factory is None:
        # 这类保护分支在教学代码里很重要。
        # 否则一旦读者忘记配置 lifespan，报错会变成晦涩的 “NoneType is not callable”。
        raise RuntimeError("数据库未初始化，请确保 FastAPI 已正确配置 lifespan")

    async with session_factory() as session:
        yield session


# ── FastAPI 应用 ──────────────────────────────────────────
app = FastAPI(title="Todo CRUD API", lifespan=lifespan)


def ok(data: Any = None, message: str = "ok") -> dict:
    return UnifiedResponse(code=0, message=message, data=data).model_dump()


def fail(code: int, message: str) -> dict:
    return UnifiedResponse(code=code, message=message).model_dump()


@app.post("/todos")
async def create_todo(body: TodoCreate, session: AsyncSession = Depends(get_db_session)):
    repo = TodoRepository(session)
    # 显式事务边界：只有真正写数据库的几行代码被包进事务。
    async with session.begin():
        todo = await repo.create(title=body.title, description=body.description)
    return ok(data=TodoResponse.model_validate(todo).model_dump(), message="创建成功")


@app.get("/todos")
async def list_todos(session: AsyncSession = Depends(get_db_session)):
    repo = TodoRepository(session)
    # 纯读请求不需要显式 begin()。
    # 让它保持无额外事务包装，可以更清楚地区分“读 Session”和“写事务”。
    todos = await repo.list_all()
    data = [TodoResponse.model_validate(t).model_dump() for t in todos]
    return ok(data=data)


@app.get("/todos/{todo_id}")
async def get_todo(todo_id: int, session: AsyncSession = Depends(get_db_session)):
    repo = TodoRepository(session)
    todo = await repo.get_by_id(todo_id)
    if todo is None:
        return JSONResponse(status_code=404, content=fail(404, "待办事项不存在"))
    return ok(data=TodoResponse.model_validate(todo).model_dump())


@app.put("/todos/{todo_id}")
async def update_todo(todo_id: int, body: TodoUpdate, session: AsyncSession = Depends(get_db_session)):
    repo = TodoRepository(session)
    async with session.begin():
        todo = await repo.update(todo_id, **body.model_dump(exclude_unset=True))
    if todo is None:
        return JSONResponse(status_code=404, content=fail(404, "待办事项不存在"))
    return ok(data=TodoResponse.model_validate(todo).model_dump(), message="更新成功")


@app.delete("/todos/{todo_id}")
async def delete_todo(todo_id: int, session: AsyncSession = Depends(get_db_session)):
    repo = TodoRepository(session)
    async with session.begin():
        deleted = await repo.delete(todo_id)
    if not deleted:
        return JSONResponse(status_code=404, content=fail(404, "待办事项不存在"))
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
        print("  开始 CRUD 集成测试")
        print("=" * 60)

        # CREATE
        print("\n▸ POST /todos — 创建待办")
        for title, desc in [("学习 SQLAlchemy", "完成异步 ORM 教程"), ("买菜", "西红柿、鸡蛋"), ("跑步", "5公里")]:
            resp = await client.post(f"{base}/todos", json={"title": title, "description": desc})
            print(f"  [{resp.status_code}]", end=" ")
            pp(resp.json())

        # LIST
        print("\n▸ GET /todos — 获取列表")
        resp = await client.get(f"{base}/todos")
        print(f"  [{resp.status_code}]")
        pp(resp.json())

        # GET by ID
        print("\n▸ GET /todos/1 — 获取详情")
        resp = await client.get(f"{base}/todos/1")
        print(f"  [{resp.status_code}]")
        pp(resp.json())

        # GET 404
        print("\n▸ GET /todos/999 — 不存在")
        resp = await client.get(f"{base}/todos/999")
        print(f"  [{resp.status_code}]")
        pp(resp.json())

        # UPDATE
        print("\n▸ PUT /todos/1 — 更新 (标记完成)")
        resp = await client.put(f"{base}/todos/1", json={"done": True, "title": "学习 SQLAlchemy (已完成)"})
        print(f"  [{resp.status_code}]")
        pp(resp.json())

        # DELETE
        print("\n▸ DELETE /todos/2 — 删除")
        resp = await client.delete(f"{base}/todos/2")
        print(f"  [{resp.status_code}]")
        pp(resp.json())

        # DELETE 404
        print("\n▸ DELETE /todos/999 — 删除不存在的")
        resp = await client.delete(f"{base}/todos/999")
        print(f"  [{resp.status_code}]")
        pp(resp.json())

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
