"""
TaskIQ 事件装饰器与 TaskiqState — @broker.on_event 结合共享状态。

目标:
    演示 @broker.on_event 装饰器与 TaskiqState 结合使用

关键概念:
    - @broker.on_event 装饰器注册事件处理器
    - TaskiqState 在 worker 启动时注入共享资源
    - 事件处理器接收 state 参数

关键 API:
    - @broker.on_event(TaskiqEvents.WORKER_STARTUP)  — 注册启动事件
    - @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)  — 注册关闭事件
    - TaskiqState                                     — Worker 共享状态
    - TaskiqDepends                                   — 在任务中注入 state

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/08_events_and_lifecycle

运行方式:
    Worker:
        taskiq worker examples.08_events_and_lifecycle.02_broker_events:broker
    Client:
        python examples/08_events_and_lifecycle/02_broker_events.py

预期现象:
    - Worker 启动时初始化 redis_pool 和 config 到 state
    - 任务执行时通过 TaskiqState 访问共享资源
    - Worker 关闭时清理 state 中的资源

生产提醒:
    - state 是 Worker 进程级别的，多个 Worker 进程各自独立
    - 重量级资源（连接池）应在 startup 中初始化，避免每次任务创建
    - shutdown 中务必关闭所有连接，防止资源泄漏

技术要点:
    - @broker.on_event 是声明式的事件注册方式
    - TaskiqState 类似 FastAPI 的 app.state，挂载任意属性
    - 多个 startup 处理器按注册顺序执行
    - 对比 Celery: Celery 用 @worker_init.connect 信号
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
    "taskiq:examples:08_events_and_lifecycle:02_broker_events",
)

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
).with_result_backend(result_backend)


# ── 2. 注册 WORKER_STARTUP — 初始化多个共享资源 ──


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def init_redis_pool(state: TaskiqState) -> None:
    """初始化 Redis 连接池 — 挂载到 state.redis_pool。"""
    print("🟢 [STARTUP] 初始化 Redis 连接池...")
    # 模拟 aioredis 连接池（实际生产中使用 redis.asyncio.ConnectionPool）
    state.redis_pool = {
        "type": "redis.asyncio.ConnectionPool",
        "url": "redis://default:123456@localhost:6379/2",
        "max_connections": 50,
        "status": "connected",
    }
    print(f"   ✅ Redis 连接池就绪: max_connections={state.redis_pool['max_connections']}")


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def init_config(state: TaskiqState) -> None:
    """加载应用配置 — 挂载到 state.config。

    多个 startup 处理器按注册顺序依次执行。
    """
    print("🟢 [STARTUP] 加载应用配置...")
    state.config = {
        "app_name": "order-service",
        "version": "2.0.0",
        "environment": "production",
        "max_retries": 3,
        "timeout_seconds": 30,
    }
    print(f"   ✅ 配置已加载: app={state.config['app_name']} v{state.config['version']}")


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def init_http_session(state: TaskiqState) -> None:
    """初始化 HTTP 客户端会话 — 挂载到 state.http_session。"""
    print("🟢 [STARTUP] 初始化 HTTP 客户端...")
    # 模拟 aiohttp.ClientSession（实际生产中使用 aiohttp 或 httpx）
    state.http_session = {
        "type": "httpx.AsyncClient",
        "base_url": "https://api.example.com",
        "timeout": 30,
        "status": "open",
    }
    print(f"   ✅ HTTP 客户端就绪: base_url={state.http_session['base_url']}")


# ── 3. 注册 WORKER_SHUTDOWN — 清理所有资源 ──


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def cleanup_resources(state: TaskiqState) -> None:
    """Worker 关闭时清理所有共享资源。"""
    print("🔴 [SHUTDOWN] 开始清理资源...")

    # 关闭 Redis 连接池
    if hasattr(state, "redis_pool"):
        state.redis_pool["status"] = "closed"
        print("   ✅ Redis 连接池已关闭")

    # 关闭 HTTP 客户端
    if hasattr(state, "http_session"):
        state.http_session["status"] = "closed"
        print("   ✅ HTTP 客户端已关闭")

    print("🔴 [SHUTDOWN] 所有资源已清理!")


# ── 4. 定义任务（通过 TaskiqState 访问共享资源） ──


@broker.task(task_name="examples.08_events_and_lifecycle.02_broker_events.get_user_profile")
async def get_user_profile(
    user_id: int,
    state: TaskiqState = TaskiqDepends(),
) -> dict:
    """获取用户资料 — 先查缓存（Redis），未命中则调用 API。

    通过 TaskiqDepends() 注入 TaskiqState，
    访问 startup 中初始化的 redis_pool、http_session、config。
    """
    print(f"📦 Worker 获取用户资料: user_id={user_id}")
    print(f"   Redis 状态: {state.redis_pool['status']}")
    print(f"   HTTP 状态: {state.http_session['status']}")
    print(f"   应用配置: {state.config['app_name']} v{state.config['version']}")

    # 模拟业务逻辑: 先查 Redis 缓存
    cache_key = f"user:{user_id}"
    print(f"   🔍 查询缓存: {cache_key}")

    # 模拟缓存未命中，调用 HTTP API
    print(f"   🌐 缓存未命中，调用 API: {state.http_session['base_url']}/users/{user_id}")

    return {
        "user_id": user_id,
        "name": f"user_{user_id}",
        "source": "api",
        "app": state.config["app_name"],
    }


@broker.task(task_name="examples.08_events_and_lifecycle.02_broker_events.batch_cache_warmup")
async def batch_cache_warmup(
    keys: list[str],
    state: TaskiqState = TaskiqDepends(),
) -> dict:
    """批量缓存预热 — 使用 Redis 连接池批量写入。"""
    print(f"📦 Worker 缓存预热: {len(keys)} 个 key")
    print(f"   Redis 连接池: max_connections={state.redis_pool['max_connections']}")

    # 模拟批量写入
    for key in keys:
        print(f"   📝 写入缓存: {key}")

    return {"keys_count": len(keys), "status": "warmed"}


# ── 5. 客户端发送任务 ──


async def main() -> None:
    """演示：Client 侧 startup/shutdown + 发送任务。"""
    print("🔵 [CLIENT] 使用 broker_session(...) 管理客户端生命周期")
    async with broker_session(broker):
        print()

        # 发送任务
        print("🚀 发送任务: get_user_profile(1001)")
        h1 = await get_user_profile.kiq(user_id=1001)
        r1 = await h1.wait_result(timeout=10)
        print(f"   task_id = {h1.task_id}")
        print(f"   result  = {r1.return_value}")
        print()

        print("🚀 发送任务: batch_cache_warmup(['product:1', 'product:2', 'product:3'])")
        h2 = await batch_cache_warmup.kiq(keys=["product:1", "product:2", "product:3"])
        r2 = await h2.wait_result(timeout=10)
        print(f"   task_id = {h2.task_id}")
        print(f"   result  = {r2.return_value}")
        print()

        print("💡 关键点:")
        print("   - @broker.on_event 是声明式事件注册，可注册多个处理器")
        print("   - 多个 WORKER_STARTUP 处理器按注册顺序依次执行")
        print("   - TaskiqState 类似 FastAPI 的 app.state，可挂载任意属性")
        print("   - 任务中通过 TaskiqDepends() 注入 TaskiqState 访问共享资源")
        print("   - 对比 Celery: Celery 用 @worker_init.connect 信号 + 全局变量")
        print("   - TaskIQ 的 state 机制更优雅，避免全局变量污染")

    print()
    print("🔵 [CLIENT] broker.shutdown()...")


if __name__ == "__main__":
    asyncio.run(main())
