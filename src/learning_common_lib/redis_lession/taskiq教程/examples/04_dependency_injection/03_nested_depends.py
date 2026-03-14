"""
TaskIQ 依赖嵌套 — 依赖链自动解析与 generator 依赖生命周期。

目标:
    演示 TaskIQ 依赖嵌套 — 依赖链自动解析与 generator 依赖生命周期

关键概念:
    - 依赖 A 依赖 B，TaskIQ 自动解析依赖链
    - async generator 依赖：yield 前是 setup，yield 后是 cleanup
    - 依赖结果缓存：同一次任务执行中，相同依赖只调用一次

关键 API:
    - TaskiqDepends                — 声明依赖注入
    - async generator dependency   — yield 模式管理资源生命周期

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/04_dependency_injection

运行方式:
    Worker:
        taskiq worker examples.04_dependency_injection.03_nested_depends:broker
    Client:
        python examples/04_dependency_injection/03_nested_depends.py

预期现象:
    - Worker 执行任务时，依赖链自动解析：get_db_url → get_db_session → task
    - async generator 依赖在任务完成后自动执行 cleanup（yield 之后的代码）

生产提醒:
    - generator 依赖适合管理需要 cleanup 的资源（数据库连接、文件句柄等）
    - 依赖缓存避免重复初始化，但仅在单次任务执行内有效

技术要点:
    - 依赖链自动解析：TaskIQ 按拓扑顺序初始化依赖
    - async generator 依赖：yield 前是 setup，yield 后是 cleanup
    - 同一次任务执行中，相同依赖只调用一次（结果缓存）
"""

from __future__ import annotations

import asyncio
import os

from taskiq import TaskiqDepends
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:examples:04_dependency_injection:03_nested_depends",
)

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
).with_result_backend(result_backend)

RESOLUTION_TRACE: list[str] = []


# ── 2. 定义嵌套依赖链 ──
# 依赖关系: get_db_url → get_db_session → task
# TaskIQ 自动按拓扑顺序解析


async def get_db_url() -> str:
    """底层依赖 — 提供数据库连接 URL。"""
    if RESOLUTION_TRACE:
        RESOLUTION_TRACE.clear()
    RESOLUTION_TRACE.append("get_db_url")
    print("🔧 [依赖层1] 获取数据库 URL...")
    return "postgresql://user:pass@localhost:5432/mydb"


async def get_db_session(
    db_url: str = TaskiqDepends(get_db_url),
):
    """中层依赖 — async generator 管理数据库会话生命周期。

    yield 前: setup（创建会话）
    yield 值: 注入到任务的对象
    yield 后: cleanup（关闭会话）
    """
    RESOLUTION_TRACE.append("get_db_session.setup")
    # ── setup 阶段 ──
    print(f"🔧 [依赖层2] 创建数据库会话, url={db_url}")
    session = {"url": db_url, "session_id": "sess-abc-123", "active": True}
    print(f"✅ [依赖层2] 会话已创建: {session['session_id']}")

    yield session  # 注入到任务

    # ── cleanup 阶段（任务完成后自动执行） ──
    RESOLUTION_TRACE.append("get_db_session.cleanup")
    print(f"🧹 [依赖层2] 关闭数据库会话: {session['session_id']}")
    session["active"] = False
    print("✅ [依赖层2] 会话已关闭")


# ── 3. 定义任务（使用嵌套依赖） ──


@broker.task(task_name="examples.04_dependency_injection.03_nested_depends.query_orders")
async def query_orders(
    customer_id: int,
    db_session: dict = TaskiqDepends(get_db_session),
) -> dict:
    """查询订单 — 自动注入数据库会话（含嵌套依赖解析）。"""
    RESOLUTION_TRACE.append("query_orders")
    print(f"📦 Worker 查询订单: customer_id={customer_id}")
    print(f"   使用会话: {db_session['session_id']}")
    print(f"   连接地址: {db_session['url']}")

    # 模拟查询
    orders = [
        {"order_id": 1001, "amount": 99.9},
        {"order_id": 1002, "amount": 199.9},
    ]
    print(f"✅ 查询到 {len(orders)} 条订单")
    return {
        "customer_id": customer_id,
        "session_id": db_session["session_id"],
        "orders": orders,
        "resolution_trace": list(RESOLUTION_TRACE),
    }


# ── 4. 客户端发送任务 ──


async def main() -> None:
    """演示：嵌套依赖链与 generator 依赖生命周期。"""
    await broker.startup()
    try:
        print("=" * 60)
        print("阶段 1: TaskIQ 先按依赖拓扑排序解析 get_db_url -> get_db_session")
        print("阶段 2: query_orders 执行结束后，再回到 generator cleanup")
        print("=" * 60)
        print("🚀 发送查询任务（Worker 端将自动解析依赖链）...")
        print("   依赖链: get_db_url → get_db_session → query_orders")
        print()

        handle = await query_orders.kiq(customer_id=42)
        result = await handle.wait_result(timeout=10)
        print(f"✅ 任务返回值: {result.return_value}")
        print()

        print("依赖生命周期（Worker 端执行顺序）:")
        print("  1. get_db_url()          -> 返回数据库 URL")
        print("  2. get_db_session()      -> setup: 创建会话（yield 前）")
        print("  3. query_orders()        -> 执行任务逻辑")
        print("  4. get_db_session()      -> cleanup: 关闭会话（yield 后）")
        print()
        print("对照结论:")
        print("  - async generator 依赖 = setup + yield + cleanup")
        print("  - 嵌套依赖由 TaskIQ 自动按拓扑顺序解析")
        print("  - 同一次任务中，相同依赖只调用一次（结果缓存）")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
