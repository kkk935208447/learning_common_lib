"""
目标: 演示多对多关系：通过关联表 (association table) 连接 Student 和 Course
关键 API: Table (关联表), relationship(secondary=...), selectinload, ForeignKey
Python 版本: 3.11+
运行命令: uv run python examples/05_relationships/02_many_to_many.py  (从 mysql_lession/ 目录)
预期现象: 创建学生、课程、关联表，插入数据并建立多对多关系，双向查询并打印
生产提醒: 关联表如需额外字段（如选课时间、成绩），应改用 Association Object 模式而非纯 secondary
"""

import asyncio

from sqlalchemy import Column, ForeignKey, String, Table, select
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    selectinload,
)

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(AsyncAttrs, DeclarativeBase):
    pass


# ── 关联表：不需要 ORM 模型，用 Table 直接定义 ──
# 这张表只有两个外键列，没有自己的主键业务字段
student_course = Table(
    "demo_student_course",
    Base.metadata,
    Column("student_id", ForeignKey("demo_students.id", ondelete="CASCADE"), primary_key=True),
    Column("course_id", ForeignKey("demo_courses.id", ondelete="CASCADE"), primary_key=True),
)


class Student(Base):
    __tablename__ = "demo_students"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), comment="学生姓名")

    # 多对多关系：通过 secondary 指定关联表
    courses: Mapped[list["Course"]] = relationship(
        secondary=student_course,
        back_populates="students",
        lazy="raise",  # 禁止隐式懒加载，强制使用显式加载策略
    )

    def __repr__(self) -> str:
        return f"<Student(id={self.id}, name={self.name!r})>"


class Course(Base):
    __tablename__ = "demo_courses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), comment="课程名称")
    credit: Mapped[int] = mapped_column(default=3, comment="学分")

    # 反向关系
    students: Mapped[list["Student"]] = relationship(
        secondary=student_course,
        back_populates="courses",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Course(id={self.id}, title={self.title!r}, credit={self.credit})>"


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    # 建表（包括关联表）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("表 demo_students, demo_courses, demo_student_course 已创建\n")

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # ── 插入学生和课程 ──
    async with session_factory() as session:
        async with session.begin():
            # 创建课程
            math = Course(title="高等数学", credit=4)
            english = Course(title="大学英语", credit=3)
            python_course = Course(title="Python 编程", credit=3)
            database = Course(title="数据库原理", credit=4)

            # 创建学生，通过 courses 列表直接建立关联
            alice = Student(name="小明", courses=[math, english, python_course])
            bob = Student(name="小红", courses=[math, python_course, database])
            charlie = Student(name="小刚", courses=[english, database])

            session.add_all([alice, bob, charlie])
        print("插入 3 个学生、4 门课程，并建立选课关系")

    # ── 从学生方向查询：每个学生选了哪些课 ──
    print("\n--- 学生 → 课程 ---")
    async with session_factory() as session:
        stmt = (
            select(Student)
            .options(selectinload(Student.courses))
            .order_by(Student.id)
        )
        result = await session.execute(stmt)
        students = result.scalars().all()

        for s in students:
            course_names = [f"{c.title}({c.credit}学分)" for c in s.courses]
            print(f"  {s.name} 选了 {len(s.courses)} 门课: {', '.join(course_names)}")

    # ── 从课程方向查询：每门课有哪些学生 ──
    print("\n--- 课程 → 学生 ---")
    async with session_factory() as session:
        stmt = (
            select(Course)
            .options(selectinload(Course.students))
            .order_by(Course.id)
        )
        result = await session.execute(stmt)
        courses = result.scalars().all()

        for c in courses:
            student_names = [s.name for s in c.students]
            print(f"  《{c.title}》有 {len(c.students)} 名学生: {', '.join(student_names)}")

    # ── 动态添加/移除关联 ──
    print("\n--- 动态修改选课关系 ---")
    async with session_factory() as session:
        async with session.begin():
            # 查询小刚，加载他的课程
            stmt = select(Student).options(selectinload(Student.courses)).where(Student.name == "小刚")
            result = await session.execute(stmt)
            xiaogang = result.scalar_one()

            # 查询 Python 编程课
            stmt2 = select(Course).where(Course.title == "Python 编程")
            result2 = await session.execute(stmt2)
            py_course = result2.scalar_one()

            # 小刚加选 Python 编程
            xiaogang.courses.append(py_course)
            print(f"  小刚加选了《{py_course.title}》")

            # 小刚退选大学英语
            eng = next(c for c in xiaogang.courses if c.title == "大学英语")
            xiaogang.courses.remove(eng)
            print(f"  小刚退选了《{eng.title}》")

    # 验证修改结果
    print("\n--- 修改后验证 ---")
    async with session_factory() as session:
        stmt = select(Student).options(selectinload(Student.courses)).where(Student.name == "小刚")
        result = await session.execute(stmt)
        xiaogang = result.scalar_one()
        course_names = [c.title for c in xiaogang.courses]
        print(f"  小刚当前选课: {', '.join(course_names)}")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("\n表已删除")

    await engine.dispose()
    print("引擎已释放")


if __name__ == "__main__":
    asyncio.run(main())
