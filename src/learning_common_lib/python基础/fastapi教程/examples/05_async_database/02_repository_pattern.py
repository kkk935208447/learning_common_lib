"""
目标: 演示 Repository 模式 + 文件型 SQLite，通过依赖注入提供数据库访问能力
关键 API: APIRouter, AsyncSession, Depends, Repository, create_async_engine
Python 版本: 3.11+
运行命令: uv run python examples/05_async_database/02_repository_pattern.py
测试命令: uv run python examples/05_async_database/02_repository_pattern_test.py
生产提醒: Repository 模式让数据访问逻辑更容易测试；这里用文件型 SQLite 模拟真实数据库持久化，并用 lifespan 管理数据库生命周期
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DB_FILE = Path(__file__).with_name("02_repository_pattern.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_FILE.as_posix()}"


class Base(DeclarativeBase):
    pass


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str] = mapped_column(String(100))


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


def get_database_file() -> Path:
    return DB_FILE


async def init_database() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def reset_database() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def dispose_database() -> None:
    await engine.dispose()


class BookRepository:
    """把所有 Book 表操作集中在一起。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, title: str, author: str) -> Book:
        book = Book(title=title, author=author)
        self.session.add(book)
        await self.session.commit()
        await self.session.refresh(book)
        return book

    async def get_by_id(self, book_id: int) -> Book | None:
        return await self.session.get(Book, book_id)

    async def list_all(self) -> list[Book]:
        result = await self.session.execute(select(Book).order_by(Book.id))
        return list(result.scalars().all())

    async def delete(self, book: Book) -> None:
        await self.session.delete(book)
        await self.session.commit()


async def get_db():
    async with async_session() as session:
        yield session


async def get_book_repo(db: AsyncSession = Depends(get_db)) -> BookRepository:
    return BookRepository(db)


class BookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    author: str = Field(min_length=1, max_length=100)


class BookOut(BaseModel):
    id: int
    title: str
    author: str

    model_config = {"from_attributes": True}


router = APIRouter(tags=["async_database"])


@router.post("/books", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def create_book(
    body: BookCreate,
    repo: BookRepository = Depends(get_book_repo),
):
    book = await repo.create(body.title, body.author)
    return BookOut.model_validate(book)


@router.get("/books", response_model=list[BookOut])
async def list_books(repo: BookRepository = Depends(get_book_repo)):
    books = await repo.list_all()
    return [BookOut.model_validate(book) for book in books]


@router.get("/books/{book_id}", response_model=BookOut)
async def get_book(book_id: int, repo: BookRepository = Depends(get_book_repo)):
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    return BookOut.model_validate(book)


@router.delete("/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(book_id: int, repo: BookRepository = Depends(get_book_repo)):
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    await repo.delete(book)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时建表，关闭时释放数据库连接。"""
    await init_database()
    yield
    await dispose_database()


def create_app() -> FastAPI:
    """创建带 lifespan 的 FastAPI 应用。"""
    app = FastAPI(
        title="02_repository_pattern — 文件型 SQLite + Repository",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


if __name__ == "__main__":
    import uvicorn

    app = create_app()
    print(f"数据库文件: {get_database_file()}")
    uvicorn.run(app, host="127.0.0.1", port=8000)
