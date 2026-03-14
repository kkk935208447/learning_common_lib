"""
FastAPI 和 TaskIQ 共享依赖 — 无需 taskiq-fastapi 包。

目标:
    演示 FastAPI 和 TaskIQ 之间共享依赖 — 无需 taskiq-fastapi 包

关键概念:
    - 手动共享依赖函数（Redis 连接池、配置等）
    - FastAPI Depends 和 TaskIQ TaskiqDepends 使用相同的依赖函数
    - worker startup 中初始化共享资源

关键 API:
    - FastAPI Depends              — FastAPI 依赖注入
    - TaskiqDepends                — TaskIQ 依赖注入
    - broker.on_event("startup")   — Worker 启动事件

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/10_fastapi_integration

运行方式:
    Worker:
        taskiq worker examples.10_fastapi_integration.02_fastapi_depends_shared:broker
    Server:
        uvicorn examples.10_fastapi_integration.02_fastapi_depends_shared:app --reload

预期现象:
    - FastAPI 端点和 TaskIQ 任务使用相同的依赖函数
    - Worker 启动时初始化共享资源
    - API 返回包含依赖注入信息的结果

生产提醒:
    - 共享依赖函数定义一次，FastAPI 和 TaskIQ 两边都用
    - 重量级资源（连接池）在各自的 startup 中初始化
    - 轻量级依赖（配置读取）可直接作为函数调用

技术要点:
    - 共享依赖的关键：依赖函数定义一次，两边都用
    - FastAPI 侧通过 Depends() 注入
    - TaskIQ 侧通过 TaskiqDepends() 注入
    - 资源初始化在各自的 startup 中完成
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from taskiq import TaskiqDepends
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
).with_result_backend(result_backend)


# ── 2. 定义共享依赖函数 ──
# 关键：依赖函数定义一次，FastAPI 和 TaskIQ 两边都用


async def get_redis_pool() -> dict:
    """获取 Redis 连接池信息 — FastAPI 和 TaskIQ 共享。"""
    print("🔧 [共享依赖] 获取 Redis 连接池...")
    return {
        "host": "localhost",
        "port": 6379,
        "pool_size": 10,
        "connected": True,
    }


async def get_app_config() -> dict:
    """获取应用配置 — FastAPI 和 TaskIQ 共享。"""
    print("🔧 [共享依赖] 加载应用配置...")
    return {
        "app_name": "order-service",
        "version": "2.0.0",
        "max_retries": 3,
        "timeout": 30,
    }


# ── 3. TaskIQ 任务（使用 TaskiqDepends 注入共享依赖） ──


@broker.task(task_name="examples.10_fastapi_integration.02_fastapi_depends_shared.background_process")
async def background_process(
    order_id: int,
    redis_pool: dict = TaskiqDepends(get_redis_pool),
    config: dict = TaskiqDepends(get_app_config),
) -> dict:
    """后台处理订单 — 通过 TaskiqDepends 注入共享依赖。"""
    print(f"📦 [Worker] 处理订单: order_id={order_id}")
    print(f"   Redis 连接池: {redis_pool}")
    print(f"   应用配置: {config}")
    return {
        "order_id": order_id,
        "app": config["app_name"],
        "redis_connected": redis_pool["connected"],
        "status": "completed",
    }


# ── 4. Worker startup 事件 — 初始化共享资源 ──


@broker.on_event("startup")
async def on_worker_startup(state) -> None:
    """Worker 启动时初始化共享资源。"""
    print("🚀 [Worker] 启动事件: 初始化共享资源...")
    # 在生产环境中，这里可以初始化连接池、加载模型等
    state.redis_info = await get_redis_pool()
    state.config = await get_app_config()
    print("✅ [Worker] 共享资源已就绪")


# ── 5. FastAPI lifespan ──


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期 — 启动时初始化 broker。"""
    print("🚀 [FastAPI] 启动: 初始化 TaskIQ broker...")
    await broker.startup()
    yield
    print("🛑 [FastAPI] 关闭: 清理 TaskIQ broker...")
    await broker.shutdown()


app = FastAPI(
    title="FastAPI + TaskIQ 共享依赖示例",
    lifespan=lifespan,
)


# ── 6. FastAPI 端点（使用 Depends 注入相同的共享依赖） ──


@app.post("/tasks/process")
async def create_task(
    order_id: int,
    config: dict = Depends(get_app_config),
) -> dict:
    """API 端点 — 使用 FastAPI Depends 注入共享依赖，然后发送任务。"""
    print(f"🌐 [FastAPI] 收到请求: order_id={order_id}")
    print(f"   注入的配置: {config}")

    handle = await background_process.kiq(order_id=order_id)
    return {
        "task_id": handle.task_id,
        "status": "queued",
        "app": config["app_name"],
        "message": f"订单 {order_id} 已提交后台处理",
    }


@app.get("/health")
async def health_check(
    redis_pool: dict = Depends(get_redis_pool),
    config: dict = Depends(get_app_config),
) -> dict:
    """健康检查 — 验证共享依赖可用。"""
    return {
        "status": "healthy",
        "app": config["app_name"],
        "redis_connected": redis_pool["connected"],
    }


# ── 7. 脚本入口 — 打印架构说明 ──


async def main() -> None:
    """打印架构说明和启动命令（不实际启动服务）。"""
    print("=" * 60)
    print("🏗️ FastAPI + TaskIQ 共享依赖架构")
    print("=" * 60)
    print()
    print("📋 核心思路: 依赖函数定义一次，两边都用")
    print()
    print("  ┌─────────────────────────────────────────────┐")
    print("  │         共享依赖函数（定义一次）              │")
    print("  │  get_redis_pool()    get_app_config()       │")
    print("  └──────────┬──────────────────┬───────────────┘")
    print("             │                  │")
    print("     ┌───────▼───────┐  ┌───────▼───────┐")
    print("     │   FastAPI     │  │   TaskIQ      │")
    print("     │  Depends()    │  │ TaskiqDepends()│")
    print("     └───────────────┘  └───────────────┘")
    print()
    print("📋 启动命令:")
    print()
    print("  1️⃣  启动 Worker:")
    print("     taskiq worker examples.10_fastapi_integration.02_fastapi_depends_shared:broker")
    print()
    print("  2️⃣  启动 FastAPI:")
    print("     uvicorn examples.10_fastapi_integration.02_fastapi_depends_shared:app --reload")
    print()
    print("📋 测试命令:")
    print()
    print('  curl -X POST "http://127.0.0.1:8000/tasks/process?order_id=1001"')
    print('  curl "http://127.0.0.1:8000/health"')
    print()
    print("💡 关键点:")
    print("  - get_redis_pool() 和 get_app_config() 只定义一次")
    print("  - FastAPI 用 Depends(get_app_config) 注入")
    print("  - TaskIQ 用 TaskiqDepends(get_app_config) 注入")
    print("  - 无需 taskiq-fastapi 包，手动共享更清晰")


if __name__ == "__main__":
    asyncio.run(main())
