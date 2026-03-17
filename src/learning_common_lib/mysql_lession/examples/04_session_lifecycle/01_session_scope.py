"""
目标: 演示 async_sessionmaker 工厂模式、session-per-request 模式、手动 begin/commit/rollback
关键 API: async_sessionmaker, session.begin(), session.commit(), session.rollback(), async with session
Python 版本: 3.11+
运行命令: uv run python examples/04_session_lifecycle/01_session_scope.py  (从 mysql_lession/ 目录)
预期现象: 展示三种 session 使用模式，每种模式下完成 CRUD 操作并打印结果
生产提醒: 推荐使用 async with session_factory() as session 模式，自动管理 close；Web 框架中一个请求对应一个 session
"""

import asyncio

from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Note(Base):
    __tablename__ = "demo_notes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(String(200), comment="笔记内容")

    def __repr__(self) -> str:
        return f"<Note(id={self.id}, content={self.content!r})>"


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        # 先删掉 Base 里声明的所有表（如果不存在就什么都不做）
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("表 demo_notes 已创建\n")

    # ── 创建 session 工厂 ──
    # async_sessionmaker 是工厂，每次调用生成一个新的 AsyncSession
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,  # commit 后不过期属性，避免异步访问报错
    )

    # ══════════════════════════════════════════════
    # 模式一：推荐 — async with session_factory() as session
    # session 退出上下文时自动 close（但不自动 commit）
    # ══════════════════════════════════════════════
    print("--- 模式一: async with session_factory() as session ---")
    async with session_factory() as session:
        note1 = Note(content="模式一：上下文管理器自动关闭 session")
        session.add(note1)
        await session.commit()  # 需要手动 commit
        print(f"  插入: {note1}")

    # ══════════════════════════════════════════════
    # 模式二：session.begin() 自动 commit/rollback
    # begin() 退出时：正常 → commit，异常 → rollback
    # ══════════════════════════════════════════════
    print("\n--- 模式二: async with session.begin() 自动提交 ---")
    async with session_factory() as session:
        async with session.begin():
            note2 = Note(content="模式二：begin() 自动提交")
            session.add(note2)
            # 不需要手动 commit，退出 begin() 上下文时自动提交
        print(f"  插入: {note2}")

    # 演示 begin() 遇到异常自动回滚
    print("\n--- 模式二（异常回滚演示） ---")
    async with session_factory() as session:
        try:
            async with session.begin():
                note_fail = Note(content="这条不会被提交")
                session.add(note_fail)
                # flush / refresh / commit 的区别（这三者经常被混用）：
                # - flush(): 把当前 Session 中“待写入”的 INSERT/UPDATE/DELETE 发送到数据库执行，但不提交事务；
                #           主要用于：提前拿到自增主键 id、尽早触发唯一/外键等约束错误、在同一事务中继续依赖已写入的数据。
                # - refresh(obj): 对 obj 再发起一次 SELECT，用数据库“最终落盘”的值覆盖/补全对象属性；
                #                常用于读取数据库端生成/更新的字段（如 DEFAULT now()、on update、触发器、计算列等）。
                # - commit(): 提交事务，使变更对其他连接可见且不可用 rollback 撤销；commit 通常会先隐式 flush。
                await session.flush()  # 先 flush 拿到 id
                print(f"  flush 后 id={note_fail.id}，但即将抛异常...")
                raise ValueError("模拟业务异常")
        except ValueError as e:
            print(f"  捕获异常: {e}")
            print("  事务已自动回滚，note_fail 不会入库")

    # ══════════════════════════════════════════════
    # 模式三：手动 begin/commit/rollback
    # 适合需要精细控制事务边界的场景
    # ══════════════════════════════════════════════
    print("\n--- 模式三: 手动 begin/commit/rollback ---")
    session = session_factory()
    try:
        await session.begin()
        note3 = Note(content="模式三：手动控制事务")
        session.add(note3)
        await session.commit()
        print(f"  插入: {note3}")
    except Exception:
        await session.rollback()
        print("  发生异常，已回滚")
    finally:
        await session.close()
        print("  session 已手动关闭")

    # ── 查询全部记录验证 ──
    print("\n--- 验证：查询全部笔记 ---")
    async with session_factory() as session:
        result = await session.execute(select(Note).order_by(Note.id))
        notes = result.scalars().all()
        for n in notes:
            print(f"  {n}")
        print(f"共 {len(notes)} 条（模式二异常回滚的那条不在其中）")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("\n表已删除")

    await engine.dispose()
    print("引擎已释放")


if __name__ == "__main__":
    asyncio.run(main())
