"""
目标: 展示 mapped_column 常见列类型映射：Integer, String, Text, Float, Numeric, Boolean, DateTime, Date, Enum, JSON
关键 API: mapped_column, String, Text, Float, Numeric, Boolean, DateTime, Date, Enum, JSON, server_default, nullable, index, unique
Python 版本: 3.11+
运行命令: uv run python examples/02_model_definition/02_mapped_column_types.py  (从 mysql_lession/ 目录)
预期现象: 创建包含多种列类型的 products 表，插入样本数据，查询并逐字段打印，最后删除表
生产提醒: Numeric 精度务必根据业务需求设置，金额类字段避免使用 Float（浮点精度丢失）
"""

import asyncio
import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    Float,
    Numeric,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(AsyncAttrs, DeclarativeBase):
    pass


# ── Python 枚举，映射到数据库 ENUM 类型 ──
class ProductStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


# ── 产品模型：展示各种列类型 ──
class Product(Base):
    __tablename__ = "demo_products"

    # --- 整型主键 ---
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # --- 定长字符串，带唯一约束和索引 ---
    sku: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, comment="商品编码"
    )

    # --- 变长字符串 ---
    name: Mapped[str] = mapped_column(String(100), comment="商品名称")

    # --- 长文本 ---
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="商品描述"
    )

    # --- 浮点数（不精确，适合科学计算） ---
    weight: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="重量(kg)"
    )

    # --- 精确小数（适合金额） ---
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), comment="价格"
    )

    # --- 布尔值 ---
    is_available: Mapped[bool] = mapped_column(
        default=True, comment="是否上架"
    )

    # --- 枚举类型 ---
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus), default=ProductStatus.DRAFT, comment="状态"
    )

    # --- JSON 类型（MySQL 5.7+ 原生支持） ---
    tags: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="标签(JSON)"
    )

    # --- 日期类型（只有日期，没有时间） ---
    launch_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, comment="上市日期"
    )

    # --- 日期时间，带服务端默认值 ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, sku={self.sku!r}, name={self.name!r})>"


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    # ── 建表 ──
    async with engine.begin() as conn:
        # 先删掉 Base 里声明的所有表（如果不存在就什么都不做）
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("表 demo_products 已创建\n")

    async_session = async_sessionmaker(engine, expire_on_commit=False)

    # ── 插入样本数据 ──
    async with async_session() as session:
        product = Product(
            sku="PHONE-001",
            name="智能手机 Pro",
            description="这是一款高性能智能手机，搭载最新处理器。",
            weight=0.185,
            price=Decimal("4999.99"),
            is_available=True,
            status=ProductStatus.ACTIVE,
            tags={"color": ["黑色", "白色"], "storage": "256GB"},
            launch_date=date(2025, 6, 1),
        )
        session.add(product)
        await session.commit()
        print(f"插入成功: {product}\n")

    # ── 查询并逐字段打印 ──
    async with async_session() as session:
        stmt = select(Product).where(Product.sku == "PHONE-001")
        result = await session.execute(stmt)
        p = result.scalar_one()

        print("=== 逐字段查看类型映射 ===")
        print(f"  id (int)            : {p.id} -> {type(p.id).__name__}")
        print(f"  sku (String)        : {p.sku} -> {type(p.sku).__name__}")
        print(f"  name (String)       : {p.name} -> {type(p.name).__name__}")
        print(f"  description (Text)  : {p.description[:20]}... -> {type(p.description).__name__}")
        print(f"  weight (Float)      : {p.weight} -> {type(p.weight).__name__}")
        print(f"  price (Numeric)     : {p.price} -> {type(p.price).__name__}")
        print(f"  is_available (Bool) : {p.is_available} -> {type(p.is_available).__name__}")
        print(f"  status (Enum)       : {p.status} -> {type(p.status).__name__}")
        print(f"  tags (JSON)         : {p.tags} -> {type(p.tags).__name__}")
        print(f"  launch_date (Date)  : {p.launch_date} -> {type(p.launch_date).__name__}")
        print(f"  created_at (DateTime): {p.created_at} -> {type(p.created_at).__name__}")

    # ── 清理 ──
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("\n表已删除")

    await engine.dispose()
    print("引擎已释放")


if __name__ == "__main__":
    asyncio.run(main())
