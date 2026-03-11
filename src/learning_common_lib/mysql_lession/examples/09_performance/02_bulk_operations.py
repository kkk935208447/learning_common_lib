"""
目标: 对比三种批量插入方式的性能差异
关键 API: session.add(), session.add_all(), insert().values()
Python 版本: 3.11+
运行命令: uv run python examples/09_performance/02_bulk_operations.py  (从 mysql_lession/ 目录)
预期现象: 依次执行三种方式各插入 1000 条记录，打印耗时对比表格
生产提醒: insert().values() 最快但绕过 ORM 事件/默认值；add_all 兼顾 ORM 特性和性能；超大批量考虑分批 + executemany
"""

import asyncio
import time
from datetime import datetime, timedelta
from random import choice, randint, seed

from sqlalchemy import DateTime, Integer, String, insert, select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"

seed(42)

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
NUM_RECORDS = 1000


class Base(DeclarativeBase):
    pass


class LogEntry(Base):
    __tablename__ = "ex09_02_log_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime)

    def __repr__(self) -> str:
        return f"LogEntry(id={self.id}, level={self.level!r})"


def make_log_objects(n: int) -> list[LogEntry]:
    """生成 n 个 LogEntry ORM 对象"""
    base_time = datetime(2024, 1, 1)
    return [
        LogEntry(
            message=f"日志消息_{i:04d}: 系统运行正常",
            level=choice(LEVELS),
            created_at=base_time + timedelta(seconds=i),
        )
        for i in range(n)
    ]


def make_log_dicts(n: int) -> list[dict]:
    """生成 n 个字典 (用于 Core insert)"""
    base_time = datetime(2024, 1, 1)
    return [
        {
            "message": f"日志消息_{i:04d}: 系统运行正常",
            "level": choice(LEVELS),
            "created_at": base_time + timedelta(seconds=i),
        }
        for i in range(n)
    ]


def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def truncate_table(engine) -> None:
    """清空表数据 (保留表结构)"""
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(LogEntry.__table__.delete())


async def count_rows(engine) -> int:
    async with AsyncSession(engine) as session:
        result = await session.execute(select(func.count()).select_from(LogEntry))
        return result.scalar_one()


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    results: list[tuple[str, float, int]] = []

    # ── 方式 1: session.add() 逐条添加 ──
    print_section(f"方式 1: session.add() 逐条添加 ({NUM_RECORDS} 条)")
    objects = make_log_objects(NUM_RECORDS)
    start = time.perf_counter()
    async with AsyncSession(engine) as session, session.begin():
        for obj in objects:
            session.add(obj)
    elapsed = time.perf_counter() - start
    count = await count_rows(engine)
    print(f"  插入 {count} 条，耗时: {elapsed:.4f} 秒")
    results.append(("session.add() 逐条", elapsed, count))
    await truncate_table(engine)

    # ── 方式 2: session.add_all() 批量添加 ──
    print_section(f"方式 2: session.add_all() 批量添加 ({NUM_RECORDS} 条)")
    objects = make_log_objects(NUM_RECORDS)
    start = time.perf_counter()
    async with AsyncSession(engine) as session, session.begin():
        session.add_all(objects)
    elapsed = time.perf_counter() - start
    count = await count_rows(engine)
    print(f"  插入 {count} 条，耗时: {elapsed:.4f} 秒")
    results.append(("session.add_all() 批量", elapsed, count))
    await truncate_table(engine)

    # ── 方式 3: insert().values() Core 级批量插入 ──
    print_section(f"方式 3: insert().values() Core 级批量 ({NUM_RECORDS} 条)")
    dicts = make_log_dicts(NUM_RECORDS)
    start = time.perf_counter()
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(insert(LogEntry), dicts)
    elapsed = time.perf_counter() - start
    count = await count_rows(engine)
    print(f"  插入 {count} 条，耗时: {elapsed:.4f} 秒")
    results.append(("insert().values() Core", elapsed, count))

    # ── 对比结果 ──
    print_section("性能对比结果")
    fastest = min(r[1] for r in results)
    print(f"\n  {'方式':<28} {'耗时':>10} {'倍率':>8} {'记录数':>8}")
    print(f"  {'-'*56}")
    for name, elapsed, count in results:
        ratio = elapsed / fastest
        print(f"  {name:<28} {elapsed:>9.4f}s {ratio:>7.1f}x {count:>8}")

    print(f"""
  总结:
  - session.add() 逐条: 每次 add 都会触发 identity map 检查，最慢
  - session.add_all(): 一次性加入，减少 Python 层循环开销
  - insert().values(): 绕过 ORM 层，直接生成批量 INSERT，最快
    但不会触发 ORM 事件 (如 before_insert)，也不返回 ORM 对象
""")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("✅ 批量插入性能对比完毕，表已清理。")


if __name__ == "__main__":
    asyncio.run(main())
