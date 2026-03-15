"""
TaskIQ Context 对象和 TaskiqState — 访问消息元数据和 worker 级共享状态。

目标:
    演示 TaskIQ Context 对象和 TaskiqState — 访问消息元数据和 worker 级共享状态

关键概念:
    - Context 对象：访问 message、broker 等运行时信息
    - TaskiqState：worker 级共享状态（在 startup 事件中初始化）
    - context.reject() / context.requeue() 控制消息确认

关键 API:
    - Context                      — 任务运行时上下文
    - TaskiqState                  — worker 级共享状态
    - TaskiqDepends(Context)       — 注入 Context 对象
    - TaskiqDepends(TaskiqState)   — 注入 TaskiqState 对象
    - context.message              — 当前消息对象（含 task_id、labels 等）
    - context.reject()             — 拒绝消息（不重试）
    - context.requeue()            — 重新入队

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/04_dependency_injection

运行方式:
    Worker:
        taskiq worker examples.04_dependency_injection.02_context_and_state:broker
    Client:
        python examples/04_dependency_injection/02_context_and_state.py

预期现象:
    - Worker 启动时执行 startup 事件，初始化共享状态
    - 任务执行时可访问 Context 元数据和 TaskiqState 共享资源

生产提醒:
    - TaskiqState 适合存放连接池、配置等 worker 级资源
    - startup/shutdown 事件确保资源正确初始化和清理

技术要点:
    - Context 是 TaskIQ 内置依赖，通过 TaskiqDepends 注入
    - TaskiqState 在 worker startup 事件中初始化，所有任务共享
    - reject() 拒绝消息（不重试），requeue() 重新入队
"""

from __future__ import annotations

import asyncio
import os

from taskiq import Context, TaskiqDepends, TaskiqState
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:examples:04_dependency_injection:02_context_and_state",
)

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
).with_result_backend(result_backend)


# ── 2. Startup 事件 — 初始化 worker 级共享状态 ──


@broker.on_event("startup")
async def startup(state: TaskiqState) -> None:
    """Worker 启动时执行 — 初始化共享资源。"""
    print("🔧 [Startup] 初始化 worker 共享状态...")
    # 模拟初始化数据库连接池
    state.db_pool = "mock_db_pool(max_size=10)"
    # 模拟加载全局配置
    state.app_config = {"env": "production", "debug": False}
    print("✅ [Startup] 共享状态初始化完成")


@broker.on_event("shutdown")
async def shutdown(state: TaskiqState) -> None:
    """Worker 关闭时执行 — 清理共享资源。"""
    print("🔧 [Shutdown] 清理 worker 共享状态...")
    state.db_pool = None
    print("✅ [Shutdown] 清理完成")


# ── 3. 定义任务 — 使用 Context ──


@broker.task(task_name="examples.04_dependency_injection.02_context_and_state.task_with_context")
async def task_with_context(
    order_id: int,
    context: Context = TaskiqDepends(),
) -> dict:
    """演示 Context 注入 — 访问消息元数据。"""
    message = context.message
    print(f"📦 Worker 执行任务: order_id={order_id}")
    print(f"   task_id = {message.task_id}")
    print(f"   task_name = {message.task_name}")
    print(f"   labels = {message.labels}")
    print("   这里读取的是当前这条消息的运行时元数据，而不是全局配置")
    return {
        "order_id": order_id,
        "task_id": message.task_id,
        "labels": message.labels,
    }


# ── 4. 定义任务 — 使用 TaskiqState ──


@broker.task(task_name="examples.04_dependency_injection.02_context_and_state.task_with_state")
async def task_with_state(
    query: str,
    state: TaskiqState = TaskiqDepends(),
) -> dict:
    """演示 TaskiqState 注入 — 访问 worker 级共享状态。"""
    print(f"📦 Worker 执行查询: query={query}")
    print(f"   db_pool = {state.db_pool}")
    print(f"   app_config = {state.app_config}")
    return {
        "query": query,
        "db_pool": state.db_pool,
        "env": state.app_config["env"],
    }


# ── 5. 客户端发送任务 ──


async def main() -> None:
    """演示：Context 和 TaskiqState 的使用。"""
    await broker.startup()
    try:
        print("=" * 60)
        print("阶段 1: Context 代表当前消息")
        print("阶段 2: TaskiqState 代表当前 worker 共享状态")
        print("=" * 60)
        print()

        # ── 5a. 发送带 labels 的任务，演示 Context ──
        print("🚀 [演示一] Context — 访问消息元数据")
        handle_ctx = await (
            task_with_context.kicker()
            .with_labels(priority="high", region="us-east-1")
            .kiq(order_id=4001)
        )
        print("   client 发送时主动附加了 labels: priority / region")
        result_ctx = await handle_ctx.wait_result(timeout=10)
        print(f"✅ 返回值: {result_ctx.return_value}")
        print()

        # ── 5b. 发送任务，演示 TaskiqState ──
        print("🚀 [演示二] TaskiqState — 访问 worker 共享状态")
        handle_state = await task_with_state.kiq(query="SELECT * FROM orders")
        result_state = await handle_state.wait_result(timeout=10)
        print(f"✅ 返回值: {result_state.return_value}")
        print()

        print("对照结论:")
        print("  - Context: 一次任务一份，重点看 task_id / labels / 当前消息")
        print("  - TaskiqState: 一个 worker 一份，重点看连接池 / 配置 / 共享资源")
        print("  - startup/shutdown 负责 TaskiqState 的生命周期")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
