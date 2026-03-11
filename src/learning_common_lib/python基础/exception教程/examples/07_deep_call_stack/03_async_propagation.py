"""
目标: 演示 async 版本的仓储层/服务层/控制器层异常传播，与同步版本 01_propagation_strategy.py 对照
关键 API: async/await, asynccontextmanager, raise from
Python 版本: 3.11+
运行命令: uv run python examples/07_deep_call_stack/03_async_propagation.py  (从 exception教程/ 目录)
预期现象: 展示异步场景下的异常传播策略——边界层转换 + 透传 + async context manager 清理
生产提醒: 异步代码的异常传播规则与同步完全一致；额外注意 async context manager 的清理逻辑
"""

from __future__ import annotations

import asyncio
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


# ============================================================
# 自定义异常
# ============================================================

@dataclass
class DatabaseError(Exception):
    """数据库层异常。"""
    code: str = "DB_ERROR"
    message: str = "数据库错误"
    detail: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


@dataclass
class ServiceError(Exception):
    """服务层异常。"""
    code: str = "SERVICE_ERROR"
    message: str = "服务错误"
    detail: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


# ============================================================
# 基础设施层：模拟异步数据库
# ============================================================

async def async_database_query(sql: str) -> dict:
    """模拟异步数据库查询。"""
    await asyncio.sleep(0.01)  # 模拟 IO
    raise ConnectionRefusedError(
        "Cannot connect to PostgreSQL: connection refused (port 5432)"
    )


# ============================================================
# 仓储层：边界转换（与同步版本策略三一致）
# ============================================================

async def async_repository_get(user_id: int) -> dict:
    """仓储层：捕获底层异常，raise from 保留异常链。"""
    try:
        return await async_database_query(
            f"SELECT * FROM users WHERE id = {user_id}"
        )
    except ConnectionRefusedError as e:
        raise DatabaseError(
            code="DB_CONN_REFUSED",
            message="数据库连接失败",
            detail={"user_id": user_id},
        ) from e


# ============================================================
# 服务层：业务逻辑，透传仓储层异常
# ============================================================

async def async_service_find(user_id: int) -> dict:
    """服务层：透传 DatabaseError，业务判断时才 raise ServiceError。"""
    data = await async_repository_get(user_id)
    if data is None:
        raise ServiceError(code="USER_NOT_FOUND", message="用户不存在")
    return data


# ============================================================
# 控制器层：不做异常处理
# ============================================================

async def async_controller_get(user_id: int) -> dict:
    """控制器层：不捕获异常，让异常冒泡到全局处理器。"""
    return await async_service_find(user_id)



# ============================================================
# async context manager：异常时的资源清理
# ============================================================

@asynccontextmanager
async def async_db_connection(dsn: str = "postgresql://localhost/demo"):
    """模拟异步数据库连接的 context manager。

    关键点: 即使 yield 之后的代码抛出异常，finally 块也会执行清理。
    与同步版本的 contextmanager 行为完全一致。
    """
    print(f"  [conn] 打开连接: {dsn}")
    conn = {"dsn": dsn, "open": True}
    try:
        yield conn
    except Exception as e:
        print(f"  [conn] 检测到异常: {type(e).__name__}: {e}")
        raise  # 重新抛出，不吞异常
    finally:
        conn["open"] = False
        print(f"  [conn] 关闭连接: {dsn}")


async def demo_async_context_manager_cleanup() -> None:
    """演示 async context manager 在异常时的清理行为。"""
    print("=" * 60)
    print("演示 2：async context manager 异常清理")
    print("=" * 60)

    try:
        async with async_db_connection() as conn:
            print(f"  [业务] 连接状态: open={conn['open']}")
            # 模拟业务代码抛出异常
            raise ServiceError(code="BIZ_ERROR", message="业务逻辑失败")
    except ServiceError as e:
        print(f"  [外层] 捕获到 ServiceError: {e}")
        print(f"  [外层] 连接已关闭（finally 保证清理）")


# ============================================================
# 演示运行
# ============================================================

async def demo_async_propagation() -> None:
    """演示 1：异步异常传播——与同步版本策略三对照。"""
    print("=" * 60)
    print("演示 1：async 异常传播（边界层转换 + raise from）")
    print("=" * 60)
    print("  对照: 01_propagation_strategy.py 策略三（同步版本）")
    print()

    try:
        await async_controller_get(user_id=1)
    except Exception:
        tb_text = traceback.format_exc()
        print(tb_text)

    print("  要点: async 代码的异常传播规则与同步完全一致")
    print("  - 仓储层: ConnectionRefusedError → DatabaseError (raise from)")
    print("  - 服务层: 透传 DatabaseError")
    print("  - 控制器层: 不捕获，冒泡到全局处理器")


async def main() -> None:
    await demo_async_propagation()
    print()
    await demo_async_context_manager_cleanup()

    print(f"\n{'=' * 60}")
    print("async 异常传播要点")
    print("=" * 60)
    print("""
  1. async 函数的异常传播规则与同步函数完全一致
     - raise from 保留异常链
     - 边界层转换，其他层透传
  2. async context manager (__aenter__/__aexit__) 的异常处理
     与同步 context manager 行为一致——finally 保证清理
  3. 额外注意点:
     - asyncio.TaskGroup 中的异常会被包装为 ExceptionGroup
       （详见 06_exception_group/02_except_star.py）
     - await 一个已取消的 task 会抛出 CancelledError
""")


if __name__ == "__main__":
    asyncio.run(main())
