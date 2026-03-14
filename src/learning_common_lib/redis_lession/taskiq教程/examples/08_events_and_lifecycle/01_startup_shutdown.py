"""
TaskIQ 生命周期事件 — Worker 和 Client 的 startup/shutdown。

目标:
    演示 TaskIQ worker 和 client 的生命周期事件

关键概念:
    - WORKER_STARTUP / WORKER_SHUTDOWN 事件
    - CLIENT_STARTUP / CLIENT_SHUTDOWN 事件（client 侧 broker.startup/shutdown）
    - 在 startup 中初始化资源，shutdown 中清理

关键 API:
    - TaskiqEvents                              — 事件枚举（WORKER_STARTUP 等）
    - @broker.on_event(TaskiqEvents.WORKER_STARTUP)  — 注册事件处理器
    - TaskiqState                               — Worker 共享状态对象
    - broker.startup() / broker.shutdown()      — Client 侧生命周期

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/08_events_and_lifecycle

运行方式:
    Worker:
        taskiq worker examples.08_events_and_lifecycle.01_startup_shutdown:broker
    Client:
        python examples/08_events_and_lifecycle/01_startup_shutdown.py

预期现象:
    - Worker 启动时打印 "数据库连接池已初始化"
    - Worker 关闭时打印 "数据库连接池已关闭"
    - 任务执行时可访问 state 中的共享资源

生产提醒:
    - startup 事件适合初始化数据库连接池、Redis 客户端、HTTP Session 等
    - shutdown 事件必须正确清理资源，避免连接泄漏
    - Client 侧需要手动调用 broker.startup() / broker.shutdown()

技术要点:
    - startup/shutdown 事件在 worker 进程启动/关闭时触发
    - 适合初始化数据库连接池、Redis 客户端等资源
    - client 侧需要手动调用 broker.startup() / broker.shutdown()
"""

from __future__ import annotations

import asyncio
import os

from taskiq import TaskiqDepends, TaskiqEvents, TaskiqState
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend
try:
    from ...templates.taskiq_app import broker_session
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates.taskiq_app import broker_session  # type: ignore[no-redef]

QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:examples:08_events_and_lifecycle:01_startup_shutdown",
)

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
).with_result_backend(result_backend)


# ── 2. 注册 WORKER_STARTUP 事件 — 初始化共享资源 ──


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def on_startup(state: TaskiqState) -> None:
    """Worker 启动时触发 — 初始化数据库连接池等共享资源。

    state 参数由 TaskIQ 自动注入，是 Worker 进程级别的共享状态。
    在 state 上挂载的对象可被所有任务访问。
    """
    print("🟢 [WORKER_STARTUP] Worker 正在启动...")

    # 模拟初始化数据库连接池
    state.db_pool = {
        "type": "asyncpg_pool",
        "host": "localhost",
        "port": 5432,
        "database": "app_db",
        "min_size": 5,
        "max_size": 20,
        "status": "connected",
    }
    print(f"   ✅ 数据库连接池已初始化: {state.db_pool['host']}:{state.db_pool['port']}")

    # 模拟初始化 Redis 缓存客户端
    state.cache_client = {
        "type": "redis",
        "url": "redis://localhost:6379/2",
        "status": "connected",
    }
    print(f"   ✅ Redis 缓存客户端已初始化: {state.cache_client['url']}")

    print("🟢 [WORKER_STARTUP] 所有资源初始化完成!")


# ── 3. 注册 WORKER_SHUTDOWN 事件 — 清理共享资源 ──


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def on_shutdown(state: TaskiqState) -> None:
    """Worker 关闭时触发 — 清理数据库连接池等共享资源。"""
    print("🔴 [WORKER_SHUTDOWN] Worker 正在关闭...")

    # 清理数据库连接池
    if hasattr(state, "db_pool"):
        state.db_pool["status"] = "closed"
        print(f"   ✅ 数据库连接池已关闭")

    # 清理 Redis 缓存客户端
    if hasattr(state, "cache_client"):
        state.cache_client["status"] = "closed"
        print(f"   ✅ Redis 缓存客户端已关闭")

    print("🔴 [WORKER_SHUTDOWN] 所有资源已清理!")


# ── 4. 定义任务（访问 state 中的共享资源） ──


@broker.task(task_name="examples.08_events_and_lifecycle.01_startup_shutdown.query_user")
async def query_user(
    user_id: int,
    state: TaskiqState = TaskiqDepends(),
) -> dict:
    """查询用户 — 使用 startup 中初始化的数据库连接池。

    TaskiqState 通过 TaskiqDepends() 注入，
    可访问 startup 事件中挂载的所有共享资源。
    """
    print(f"📦 Worker 查询用户: user_id={user_id}")
    print(f"   数据库连接池状态: {state.db_pool['status']}")
    print(f"   缓存客户端状态: {state.cache_client['status']}")

    # 模拟数据库查询
    return {
        "user_id": user_id,
        "name": f"user_{user_id}",
        "db_pool": state.db_pool["status"],
        "cache": state.cache_client["status"],
    }


@broker.task(task_name="examples.08_events_and_lifecycle.01_startup_shutdown.update_cache")
async def update_cache(
    key: str,
    value: str,
    state: TaskiqState = TaskiqDepends(),
) -> dict:
    """更新缓存 — 使用 startup 中初始化的 Redis 客户端。"""
    print(f"📦 Worker 更新缓存: {key}={value}")
    print(f"   缓存客户端: {state.cache_client['url']}")
    return {"key": key, "value": value, "status": "cached"}


# ── 5. 客户端发送任务 ──


async def main() -> None:
    """演示：Client 侧的 startup/shutdown 和任务发送。"""
    print("🔵 [CLIENT] 使用 broker_session(...) 管理客户端生命周期")
    async with broker_session(broker):
        print("🔵 [CLIENT] Broker 已启动")
        print()

        # 发送任务
        print("🚀 发送任务: query_user(1001)")
        h1 = await query_user.kiq(user_id=1001)
        r1 = await h1.wait_result(timeout=10)
        print(f"   task_id = {h1.task_id}")
        print(f"   result  = {r1.return_value}")
        print()

        print("🚀 发送任务: update_cache('session:1001', 'active')")
        h2 = await update_cache.kiq(key="session:1001", value="active")
        r2 = await h2.wait_result(timeout=10)
        print(f"   task_id = {h2.task_id}")
        print(f"   result  = {r2.return_value}")
        print()

        print("💡 关键点:")
        print("   - WORKER_STARTUP: Worker 进程启动时触发，适合初始化连接池等资源")
        print("   - WORKER_SHUTDOWN: Worker 进程关闭时触发，适合清理资源")
        print("   - TaskiqState: Worker 进程级共享状态，startup 中挂载，任务中使用")
        print("   - Client 侧: 推荐用 async with broker_session(...) 管理连接")
        print("   - 对比 Celery: Celery 用 worker_init/worker_shutdown 信号")

    print()
    print("🔵 [CLIENT] Broker 已关闭")


if __name__ == "__main__":
    asyncio.run(main())
