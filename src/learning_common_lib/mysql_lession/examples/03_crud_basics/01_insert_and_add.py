"""
目标: 演示 add/add_all/flush/insert 四种插入方式的区别与用法
关键 API: session.add(), session.add_all(), session.flush(), insert().values()
Python 版本: 3.11+
运行命令: uv run python examples/03_crud_basics/01_insert_and_add.py  (从 mysql_lession/ 目录)
预期现象: 分别用四种方式插入数据，flush 后可拿到 id 但尚未提交，insert 批量插入效率最高，最后打印全部记录
生产提醒: add/add_all 适合需要 ORM 对象的场景；insert().values() 适合纯批量写入不需要返回对象的场景
"""

import asyncio

from sqlalchemy import String, insert, select
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "demo_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), comment="任务标题")
    done: Mapped[bool] = mapped_column(default=False, comment="是否完成")

    def __repr__(self) -> str:
        return f"<Task(id={self.id}, title={self.title!r}, done={self.done})>"


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    # 建表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("表 demo_tasks 已创建\n")

    async_session = async_sessionmaker(engine, expire_on_commit=False)

    # ══════════════════════════════════════
    # 方式一：session.add() 单条插入
    # ══════════════════════════════════════
    async with async_session() as session:
        task1 = Task(title="学习 SQLAlchemy", done=False)
        session.add(task1)
        await session.commit()
        print(f"[add] 插入单条: {task1}")

    # ══════════════════════════════════════
    # 方式二：session.add_all() 批量插入
    # ══════════════════════════════════════
    async with async_session() as session:
        tasks = [
            Task(title="阅读文档", done=False),
            Task(title="编写测试", done=True),
            Task(title="代码审查", done=False),
        ]
        session.add_all(tasks)
        await session.commit()
        print(f"[add_all] 批量插入 {len(tasks)} 条:")
        for t in tasks:
            print(f"  {t}")

    # ══════════════════════════════════════
    # 方式三：session.flush() — 提前拿到 id
    # ══════════════════════════════════════
    async with async_session() as session:
        async with session.begin():  # session.begin() 上下文退出时自动 commit
            task_flush = Task(title="需要提前拿 id 的任务", done=False)
            session.add(task_flush)

            # flush 会发送 INSERT 到数据库，但不提交事务
            # 此时可以拿到数据库生成的 id
            await session.flush()
            print(f"\n[flush] flush 后拿到 id: {task_flush.id}（事务尚未提交）")
            print(f"  可以用这个 id 做后续关联操作，比如插入子表")

        # session.begin() 上下文退出时自动 commit
        print(f"[flush] 事务已提交: {task_flush}")

    # ══════════════════════════════════════
    # 方式四：insert().values() Core 级批量插入
    # ══════════════════════════════════════
    async with async_session() as session:
        stmt = insert(Task).values(
            [
                {"title": "部署上线", "done": False},
                {"title": "监控告警", "done": False},
                {"title": "性能优化", "done": True},
            ]
        )
        await session.execute(stmt)
        await session.commit()
        print(f"\n[insert().values()] Core 级批量插入 3 条（不返回 ORM 对象）")

    # ══════════════════════════════════════
    # 查询全部记录
    # ══════════════════════════════════════
    async with async_session() as session:
        result = await session.execute(select(Task).order_by(Task.id))
        all_tasks = result.scalars().all()
        print(f"\n全部记录（共 {len(all_tasks)} 条）:")
        for t in all_tasks:
            status = "已完成" if t.done else "未完成"
            print(f"  id={t.id}  {t.title:<20s}  [{status}]")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("\n表已删除")

    await engine.dispose()
    print("引擎已释放")


if __name__ == "__main__":
    asyncio.run(main())
