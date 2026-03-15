"""
TaskIQ 依赖注入基础 — TaskiqDepends 的基本用法。

目标:
    演示 TaskIQ 依赖注入基础 — TaskiqDepends 的基本用法

关键概念:
    - TaskiqDepends 类比 FastAPI 的 Depends
    - 注入外部资源（Redis 客户端、配置等）
    - 依赖函数可以是 async def

关键 API:
    - TaskiqDepends                — 声明依赖注入
    - async def dependency()       — 依赖函数（同步/异步均可）

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/04_dependency_injection

运行方式:
    Worker:
        taskiq worker examples.04_dependency_injection.01_depends_basics:broker
    Client:
        python examples/04_dependency_injection/01_depends_basics.py

预期现象:
    - Worker 执行任务时自动调用依赖函数，注入配置和 Redis 客户端信息
    - Client 显示任务返回值，包含注入的配置和 Redis 信息

生产提醒:
    - 依赖函数在每次任务执行时调用，注意性能开销
    - 重量级资源（连接池等）建议用 startup 事件初始化，通过 TaskiqState 共享

技术要点:
    - 依赖注入是 TaskIQ 的核心特色，Celery 没有对应功能
    - 依赖函数在每次任务执行时调用
    - 支持 async generator 依赖（自动 cleanup）
"""

from __future__ import annotations

import asyncio
import os

from taskiq import TaskiqDepends
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:examples:04_dependency_injection:01_depends_basics",
)

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
).with_result_backend(result_backend)

DEPENDENCY_STEP = 0


def next_step(label: str) -> str:
    """给依赖解析过程打序号，方便观察运行顺序。"""
    global DEPENDENCY_STEP
    DEPENDENCY_STEP += 1
    return f"[{DEPENDENCY_STEP}] {label}"


# ── 2. 定义依赖函数 ──


async def get_config() -> dict:
    """获取应用配置 — 模拟从配置中心读取。"""
    print(f"🔧 {next_step('解析依赖 get_config')} -> 加载应用配置")
    return {
        "app_name": "order-service",
        "version": "1.0.0",
        "max_retries": 3,
    }


async def get_redis_client() -> dict:
    """获取 Redis 客户端信息 — 模拟连接（不实际连接）。"""
    print(f"🔧 {next_step('解析依赖 get_redis_client')} -> 获取 Redis 客户端信息")
    return {
        "host": "localhost",
        "port": 6379,
        "db": 0,
        "connected": True,
    }


# ── 3. 定义任务（使用依赖注入） ──


@broker.task(task_name="examples.04_dependency_injection.01_depends_basics.process_with_deps")
async def process_with_deps(
    order_id: int,
    config: dict = TaskiqDepends(get_config),
    redis_info: dict = TaskiqDepends(get_redis_client),
) -> dict:
    """处理订单 — 自动注入配置和 Redis 客户端。"""
    print(f"🧭 {next_step('进入任务 process_with_deps')}")
    print(f"📦 Worker 处理订单: order_id={order_id}")
    print(f"   注入的配置: {config}")
    print(f"   注入的 Redis: {redis_info}")
    return {
        "order_id": order_id,
        "app": config["app_name"],
        "redis_connected": redis_info["connected"],
        "status": "completed",
        "dependency_order": DEPENDENCY_STEP,
    }


# ── 4. 客户端发送任务 ──


async def main() -> None:
    """演示：依赖注入基础用法。"""
    await broker.startup()
    try:
        print("=" * 60)
        print("阶段 1: client 只传业务参数，worker 负责补齐依赖")
        print("=" * 60)
        print("🚀 发送任务（Worker 端将自动注入依赖）...")
        # 客户端只传业务参数，依赖参数由 Worker 端自动注入
        handle = await process_with_deps.kiq(order_id=3001)
        print(f"   task_id = {handle.task_id}")
        print()

        result = await handle.wait_result(timeout=10)
        print(f"✅ 任务返回值: {result.return_value}")
        print()
        print("对照结论:")
        print("  - client 侧只发送 order_id=3001")
        print("  - worker 侧先解析 get_config / get_redis_client，再进入任务函数")
        print("  - 类比 FastAPI 的 Depends()，TaskIQ 用 TaskiqDepends() 声明依赖")
        print("  - Celery 没有同等级的内置依赖注入能力")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
