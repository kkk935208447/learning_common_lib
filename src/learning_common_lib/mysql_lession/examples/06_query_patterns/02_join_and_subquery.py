"""
目标: 演示 SQLAlchemy 2.0 异步 ORM 的 join / outerjoin / subquery / exists 用法
关键 API: join(), outerjoin(), select().select_from(), scalar_subquery(), exists()
Python 版本: 3.11+
运行命令: uv run python examples/06_query_patterns/02_join_and_subquery.py  (从 mysql_lession/ 目录)
预期现象: 依次打印内连接、左外连接、标量子查询、exists 相关子查询的结果
生产提醒: 多表 join 时注意索引覆盖；子查询在大数据量下可能不如 join 高效，需结合 EXPLAIN 分析
"""

import asyncio

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    func,
    select,
    exists,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


# ── 模型定义 ──────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class Department(Base):
    __tablename__ = "ex06_02_department"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)

    employees: Mapped[list["Employee"]] = relationship(back_populates="department_rel")

    def __repr__(self) -> str:
        return f"Department(id={self.id}, name={self.name!r})"


class Employee(Base):
    __tablename__ = "ex06_02_employee"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("ex06_02_department.id"), nullable=True)
    salary: Mapped[int] = mapped_column(Integer, default=0)

    department_rel: Mapped[Department | None] = relationship(back_populates="employees")

    def __repr__(self) -> str:
        return f"Employee(id={self.id}, name={self.name!r}, dept_id={self.department_id}, salary={self.salary})"


# ── 辅助 ──────────────────────────────────────────────────
def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ── 主逻辑 ────────────────────────────────────────────────
async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # 插入示例数据
    async with AsyncSession(engine) as session, session.begin():
        eng = Department(name="Engineering")
        mkt = Department(name="Marketing")
        hr = Department(name="HR")
        finance = Department(name="Finance")  # 没有员工的部门
        session.add_all([eng, mkt, hr, finance])
        await session.flush()  # 获取 id

        session.add_all([
            Employee(name="张三", department_id=eng.id, salary=15000),
            Employee(name="李四", department_id=eng.id, salary=18000),
            Employee(name="王五", department_id=mkt.id, salary=12000),
            Employee(name="赵六", department_id=hr.id, salary=11000),
            Employee(name="孙七", department_id=None, salary=9000),  # 无部门
        ])

    async with AsyncSession(engine) as session:
        # ── 1. join() 内连接 ──
        print_section("1. join() — 内连接 (只返回有部门的员工)")
        stmt = (
            select(Employee.name, Department.name.label("dept_name"))
            .join(Department, Employee.department_id == Department.id)
        )
        rows = (await session.execute(stmt)).all()
        for r in rows:
            print(f"  员工={r.name}, 部门={r.dept_name}")

        # ── 2. outerjoin() 左外连接 ──
        print_section("2. outerjoin() — 左外连接 (包含无部门的员工)")
        stmt = (
            select(Employee.name, Department.name.label("dept_name"))
            .outerjoin(Department, Employee.department_id == Department.id)
        )
        rows = (await session.execute(stmt)).all()
        for r in rows:
            print(f"  员工={r.name}, 部门={r.dept_name or '(无部门)'}")

        # ── 3. outerjoin 反向: 包含无员工的部门 ──
        print_section("3. select_from() + outerjoin — 包含无员工的部门")
        stmt = (
            select(Department.name.label("dept_name"), Employee.name.label("emp_name"))
            .select_from(Department)
            .outerjoin(Employee, Department.id == Employee.department_id)
        )
        rows = (await session.execute(stmt)).all()
        for r in rows:
            print(f"  部门={r.dept_name}, 员工={r.emp_name or '(无员工)'}")

        # ── 4. 标量子查询 (scalar_subquery) ──
        print_section("4. scalar_subquery() — 每个部门的平均薪资")
        avg_sub = (
            select(func.avg(Employee.salary))
            .where(Employee.department_id == Department.id)
            .correlate(Department)
            .scalar_subquery()
            .label("avg_salary")
        )
        stmt = select(Department.name, avg_sub)
        rows = (await session.execute(stmt)).all()
        for r in rows:
            avg_val = f"{float(r.avg_salary):,.0f}" if r.avg_salary else "N/A"
            print(f"  部门={r.name}, 平均薪资={avg_val}")

        # ── 5. exists() 相关子查询 ──
        print_section("5. exists() — 查找有员工的部门")
        emp_exists = (
            exists()
            .where(Employee.department_id == Department.id)
        )
        stmt = select(Department).where(emp_exists)
        depts = (await session.execute(stmt)).scalars().all()
        for d in depts:
            print(f"  有员工的部门: {d.name}")

        print("\n▸ 取反 ~exists(): 查找没有员工的部门")
        stmt = select(Department).where(~emp_exists)
        depts = (await session.execute(stmt)).scalars().all()
        for d in depts:
            print(f"  无员工的部门: {d.name}")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("\n✅ join / subquery 演示完毕，表已清理。")


if __name__ == "__main__":
    asyncio.run(main())
