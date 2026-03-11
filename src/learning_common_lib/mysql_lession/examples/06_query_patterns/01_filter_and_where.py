"""
目标: 演示 SQLAlchemy 2.0 异步 ORM 的各种查询过滤方式
关键 API: where(), filter_by(), in_(), like(), between(), and_(), or_()
Python 版本: 3.11+
运行命令: uv run python examples/06_query_patterns/01_filter_and_where.py  (从 mysql_lession/ 目录)
预期现象: 依次打印各种过滤条件的查询结果，每组查询前有标题说明
生产提醒: like() 中的 % 通配符来自用户输入时务必转义，防止 SQL 注入；大表查询务必加索引
"""

import asyncio
from datetime import date, timedelta

from sqlalchemy import (
    String,
    Integer,
    Date,
    Numeric,
    and_,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"

# ── 模型定义 ──────────────────────────────────────────────
class Base(DeclarativeBase):
    pass

class Employee(Base):
    __tablename__ = "ex06_01_employee"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    department: Mapped[str] = mapped_column(String(50))
    salary: Mapped[float] = mapped_column(Numeric(10, 2))
    hire_date: Mapped[date] = mapped_column(Date)

    def __repr__(self) -> str:
        return (
            f"Employee(id={self.id}, name={self.name!r}, "
            f"dept={self.department!r}, salary={self.salary}, "
            f"hire_date={self.hire_date})"
        )

# ── 示例数据 ──────────────────────────────────────────────
SAMPLE_EMPLOYEES = [
    Employee(name="张三", department="Engineering", salary=15000, hire_date=date(2020, 3, 15)),
    Employee(name="李四", department="Engineering", salary=18000, hire_date=date(2019, 7, 1)),
    Employee(name="王五", department="Marketing", salary=12000, hire_date=date(2021, 1, 10)),
    Employee(name="赵六", department="Marketing", salary=13000, hire_date=date(2020, 6, 20)),
    Employee(name="孙七", department="HR", salary=11000, hire_date=date(2022, 2, 28)),
    Employee(name="周八", department="HR", salary=10500, hire_date=date(2023, 5, 5)),
    Employee(name="吴九", department="Engineering", salary=22000, hire_date=date(2018, 11, 11)),
    Employee(name="郑十", department="Finance", salary=16000, hire_date=date(2021, 8, 8)),
    Employee(name="陈十一", department="Finance", salary=17000, hire_date=date(2019, 4, 4)),
    Employee(name="林十二", department="Engineering", salary=20000, hire_date=date(2020, 9, 9)),
    Employee(name="黄十三", department="Marketing", salary=14000, hire_date=date(2022, 12, 1)),
]

# ── 辅助函数 ──────────────────────────────────────────────
def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def print_rows(rows: list) -> None:
    for row in rows:
        print(f"  {row}")
    if not rows:
        print("  (无结果)")

# ── 主逻辑 ────────────────────────────────────────────────
async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    # 建表 & 插入数据
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session, session.begin():
        session.add_all(SAMPLE_EMPLOYEES)

    async with AsyncSession(engine) as session:
        # ── 1. where() 基本比较 ──
        print_section("1. where() 基本比较运算符")

        print("\n▸ salary == 15000:")
        stmt = select(Employee).where(Employee.salary == 15000)
        result = await session.execute(stmt)
        print_rows(result.scalars().all())

        print("\n▸ salary != 15000:")
        stmt = select(Employee).where(Employee.salary != 15000)
        result = await session.execute(stmt)
        print_rows(result.scalars().all())

        print("\n▸ salary > 17000:")
        stmt = select(Employee).where(Employee.salary > 17000)
        result = await session.execute(stmt)
        print_rows(result.scalars().all())

        print("\n▸ salary < 12000:")
        stmt = select(Employee).where(Employee.salary < 12000)
        result = await session.execute(stmt)
        print_rows(result.scalars().all())

        # ── 2. filter_by() 关键字过滤 ──
        print_section("2. filter_by() — 按关键字过滤")
        stmt = select(Employee).filter_by(department="Engineering")
        result = await session.execute(stmt)
        print_rows(result.scalars().all())

        # ── 3. in_() ──
        print_section("3. in_() — 集合匹配")
        target_depts = ["Engineering", "Finance"]
        print(f"\n▸ department in {target_depts}:")
        stmt = select(Employee).where(Employee.department.in_(target_depts))
        result = await session.execute(stmt)
        print_rows(result.scalars().all())

        # ── 4. like() ──
        print_section("4. like() — 模糊匹配")
        print("\n▸ name like '张%':")
        stmt = select(Employee).where(Employee.name.like("张%"))
        result = await session.execute(stmt)
        print_rows(result.scalars().all())

        print("\n▸ name like '%十%' (名字含'十'):")
        stmt = select(Employee).where(Employee.name.like("%十%"))
        result = await session.execute(stmt)
        print_rows(result.scalars().all())

        # ── 5. between() ──
        print_section("5. between() — 范围查询")
        low, high = date(2020, 1, 1), date(2021, 12, 31)
        print(f"\n▸ hire_date between {low} and {high}:")
        stmt = select(Employee).where(Employee.hire_date.between(low, high))
        result = await session.execute(stmt)
        print_rows(result.scalars().all())

        # ── 6. and_() / or_() 组合 ──
        print_section("6. and_() / or_() — 组合条件")

        print("\n▸ and_(): Engineering 且 salary > 16000:")
        stmt = select(Employee).where(
            and_(
                Employee.department == "Engineering",
                Employee.salary > 16000,
            )
        )
        result = await session.execute(stmt)
        print_rows(result.scalars().all())

        print("\n▸ or_(): HR 或 salary > 19000:")
        stmt = select(Employee).where(
            or_(
                Employee.department == "HR",
                Employee.salary > 19000,
            )
        )
        result = await session.execute(stmt)
        print_rows(result.scalars().all())

        print("\n▸ 嵌套组合: (Engineering 且 salary>16000) 或 (Marketing 且 hire_date>2021-01-01):")
        stmt = select(Employee).where(
            or_(
                and_(Employee.department == "Engineering", Employee.salary > 16000),
                and_(Employee.department == "Marketing", Employee.hire_date > date(2021, 1, 1)),
            )
        )
        result = await session.execute(stmt)
        print_rows(result.scalars().all())

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("\n✅ 所有查询演示完毕，表已清理。")


if __name__ == "__main__":
    asyncio.run(main())
