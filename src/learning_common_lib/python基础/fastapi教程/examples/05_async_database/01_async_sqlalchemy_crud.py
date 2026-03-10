"""
目标: 演示 async SQLAlchemy + 文件型 SQLite 的完整 CRUD
关键 API: APIRouter, AsyncSession, create_async_engine, select, HTTPException
Python 版本: 3.11+
运行命令: uv run python examples/05_async_database/01_async_sqlalchemy_crud.py
测试命令: uv run python examples/05_async_database/01_async_sqlalchemy_crud_test.py
生产提醒: 这里用文件型 SQLite 模拟真实数据库持久化；并用 lifespan 管理数据库初始化与关闭
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ---------------------------------------------------------------------------
# 数据库配置
#
# 这里不再使用 :memory:，而是使用当前文件同目录下的 .db 文件。
# 这样测试时可以模拟“服务重启后数据仍然存在”的真实数据库效果。
# ---------------------------------------------------------------------------

DB_FILE = Path(__file__).with_name("01_async_sqlalchemy_crud.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_FILE.as_posix()}"


class Base(DeclarativeBase):
    pass


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    done: Mapped[bool] = mapped_column(default=False)


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


def get_database_file() -> Path:
    """返回当前示例实际使用的数据库文件路径。"""
    return DB_FILE


async def init_database() -> None:
    """初始化数据库表。服务启动前调用。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def reset_database() -> None:
    """
    清空数据库并重新建表。

    测试时使用它来确保每次从干净状态开始。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def dispose_database() -> None:
    """关闭连接池。测试结束或服务退出时调用。"""
    await engine.dispose()


async def get_db():
    """每个请求获取一个独立的 AsyncSession。"""
    async with async_session() as session:
        yield session


class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    done: bool | None = None


class TodoOut(BaseModel):
    id: int
    title: str
    done: bool

    model_config = {"from_attributes": True}


router = APIRouter(tags=["async_database"])


@router.post("/todos", response_model=TodoOut, status_code=status.HTTP_201_CREATED)
async def create_todo(body: TodoCreate, db: AsyncSession = Depends(get_db)):
    todo = Todo(title=body.title, done=False)
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return TodoOut.model_validate(todo)


@router.get("/todos", response_model=list[TodoOut])
async def list_todos(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Todo).order_by(Todo.id))
    todos = result.scalars().all()
    return [TodoOut.model_validate(todo) for todo in todos]


@router.get("/todos/{todo_id}", response_model=TodoOut)
async def get_todo(todo_id: int, db: AsyncSession = Depends(get_db)):
    todo = await db.get(Todo, todo_id)
    if not todo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found",
        )
    return TodoOut.model_validate(todo)


@router.patch("/todos/{todo_id}", response_model=TodoOut)
async def update_todo(
    todo_id: int,
    body: TodoUpdate,
    db: AsyncSession = Depends(get_db),
):
    todo = await db.get(Todo, todo_id)
    if not todo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found",
        )

    if body.title is not None:
        todo.title = body.title
    if body.done is not None:
        todo.done = body.done

    await db.commit()
    await db.refresh(todo)
    return TodoOut.model_validate(todo)


@router.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(todo_id: int, db: AsyncSession = Depends(get_db)):
    todo = await db.get(Todo, todo_id)
    if not todo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found",
        )

    await db.delete(todo)
    await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时建表，关闭时释放数据库连接。"""
    await init_database()
    yield
    await dispose_database()


def create_app() -> FastAPI:
    """创建带 lifespan 的 FastAPI 应用。"""
    app = FastAPI(
        title="01_async_sqlalchemy_crud — 文件型 SQLite CRUD",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


if __name__ == "__main__":
    import uvicorn

    app = create_app()
    print(f"数据库文件: {get_database_file()}")
    uvicorn.run(app, host="127.0.0.1", port=8000)
