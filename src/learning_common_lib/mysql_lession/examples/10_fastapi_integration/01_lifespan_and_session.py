"""
目标: 演示 FastAPI lifespan 管理引擎生命周期 + Depends 注入异步 session
关键 API: FastAPI(lifespan=...), async_sessionmaker, Depends, asynccontextmanager
Python 版本: 3.11+
运行命令: uv run python examples/10_fastapi_integration/01_lifespan_and_session.py  (从 mysql_lession/ 目录)
预期现象: 启动 uvicorn 服务，自动运行 httpx 测试 (POST 创建 + GET 列表 + GET 详情)，打印响应后关闭
生产提醒: 生产环境应将 engine/session_factory 放入独立模块；lifespan 中做 create_all 仅适合开发，生产用 Alembic 迁移
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Integer, String, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"

# ── 全局变量 (lifespan 中初始化) ──────────────────────────
engine = None
session_factory: async_sessionmaker[AsyncSession] | None = None


# ── ORM 模型 ──────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "ex10_01_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(200), default="")

    def __repr__(self) -> str:
        return f"Item(id={self.id}, name={self.name!r})"


# ── Pydantic 请求/响应模型 ────────────────────────────────
class ItemCreate(BaseModel):
    name: str
    description: str = ""


class ItemResponse(BaseModel):
    id: int
    name: str
    description: str

    model_config = {"from_attributes": True}


# ── Lifespan: 管理引擎生命周期 ────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, session_factory
    print("🚀 启动: 创建引擎和表...")
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield  # 应用运行中

    print("🛑 关闭: 销毁引擎...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Session 依赖注入 ──────────────────────────────────────
async def get_db_session():
    """每个请求一个 session，请求结束自动关闭"""
    async with session_factory() as session:
        yield session


# ── FastAPI 应用 ──────────────────────────────────────────
app = FastAPI(title="Item API", lifespan=lifespan)


@app.post("/items", response_model=ItemResponse, status_code=201)
async def create_item(body: ItemCreate, session: AsyncSession = Depends(get_db_session)):
    """创建物品"""
    item = Item(name=body.name, description=body.description)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@app.get("/items", response_model=list[ItemResponse])
async def list_items(session: AsyncSession = Depends(get_db_session)):
    """获取所有物品"""
    result = await session.execute(select(Item))
    return result.scalars().all()


@app.get("/items/{item_id}", response_model=ItemResponse)
async def get_item(item_id: int, session: AsyncSession = Depends(get_db_session)):
    """按 ID 获取物品"""
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="物品不存在")
    return item


# ── 测试函数 ──────────────────────────────────────────────
async def run_tests():
    """使用 httpx 测试所有端点"""
    import httpx

    await asyncio.sleep(0.5)  # 等待服务器启动
    base = "http://127.0.0.1:8000"

    async with httpx.AsyncClient() as client:
        print("\n" + "=" * 60)
        print("  开始 httpx 集成测试")
        print("=" * 60)

        # POST 创建
        for name, desc in [("笔记本电脑", "16寸 M3 芯片"), ("无线耳机", "降噪蓝牙"), ("机械键盘", "红轴 87键")]:
            resp = await client.post(f"{base}/items", json={"name": name, "description": desc})
            print(f"\n  POST /items → {resp.status_code}")
            print(f"    响应: {resp.json()}")

        # GET 列表
        resp = await client.get(f"{base}/items")
        print(f"\n  GET /items → {resp.status_code}")
        for item in resp.json():
            print(f"    {item}")

        # GET 详情
        resp = await client.get(f"{base}/items/1")
        print(f"\n  GET /items/1 → {resp.status_code}")
        print(f"    响应: {resp.json()}")

        # GET 404
        resp = await client.get(f"{base}/items/999")
        print(f"\n  GET /items/999 → {resp.status_code}")
        print(f"    响应: {resp.json()}")

        print("\n  ✅ 测试完成!")


# ── 入口 ──────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    import threading

    # 在后台线程运行测试，主线程运行 uvicorn
    def start_tests():
        loop = asyncio.new_event_loop()
        loop.run_until_complete(run_tests())
        # 测试完成后关闭服务器
        import os, signal
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=start_tests, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
