"""
解决什么问题: FastAPI 与 Celery 的集成层，提供生命周期管理、依赖注入、异步任务派发、状态轮询
输入输出约定: celery_lifespan 管理 Celery App + Redis 连接生命周期；
    get_celery() / get_redis() 作为 Depends 注入；send_task() 异步派发任务；
    /tasks/{task_id}/status 轮询任务状态
失败策略: Celery/Redis 未初始化时抛出 RuntimeError；send_task 透传 Celery 异常
不适用场景: 非 FastAPI 框架；不需要 HTTP 轮询的场景（可用 WebSocket 或回调替代）

集成模式:
  FastAPI lifespan → 初始化 Celery App + Redis 连接
  Depends(get_celery) → 注入 Celery App
  Depends(get_redis) → 注入同步 Redis 客户端（用于企业级分布式锁）
  send_task() → asyncio.to_thread 包装，不阻塞事件循环
  GET /tasks/{task_id}/status → 轮询任务执行状态
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Request

try:
    from .celery_app import init_celery_app
    from .celery_config import CeleryConfig
    from .distributed_lock import async_distributed_lock
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.celery_app import init_celery_app  # type: ignore[no-redef]
    from templates.celery_config import CeleryConfig  # type: ignore[no-redef]
    from templates.distributed_lock import async_distributed_lock  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# State keys（绑定到 app.state，避免模块级全局变量）
# ---------------------------------------------------------------------------

_CELERY_STATE_KEY = "celery_app"
_REDIS_STATE_KEY = "redis_client"


def _build_task_status_response(task_id: str, celery_app: Any) -> dict[str, Any]:
    """在线程中读取 AsyncResult，避免在 async 路由里阻塞事件循环。"""
    from celery.result import AsyncResult

    result = AsyncResult(task_id, app=celery_app)
    response: dict[str, Any] = {
        "task_id": task_id,
        "status": result.status,
    }
    if result.ready():
        if result.successful():
            response["result"] = result.result
        else:
            response["error"] = str(result.result)
    return response


# ---------------------------------------------------------------------------
# Lifespan — 管理 Celery App + Redis 连接
# ---------------------------------------------------------------------------


@asynccontextmanager
async def celery_lifespan(app: Any) -> AsyncGenerator[None, None]:
    """FastAPI 生命周期管理器，启动时初始化 Celery App 和 Redis 连接。

    用法:
        from fastapi import FastAPI
        app = FastAPI(lifespan=celery_lifespan)
    """
    import redis

    # 启动阶段
    celery_app = init_celery_app(name="web", config=CeleryConfig)
    redis_url = CeleryConfig.redis_lock_url  # 使用专用锁 Redis 连接
    redis_client = redis.Redis.from_url(redis_url, decode_responses=True)

    setattr(app.state, _CELERY_STATE_KEY, celery_app)
    setattr(app.state, _REDIS_STATE_KEY, redis_client)
    print("🚀 Celery App + Redis 连接已初始化")

    try:
        yield
    finally:
        # 关闭阶段
        await asyncio.to_thread(redis_client.close)
        setattr(app.state, _CELERY_STATE_KEY, None)
        setattr(app.state, _REDIS_STATE_KEY, None)
        print("🔌 Celery App + Redis 连接已释放")


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------


def get_celery(request: Request) -> Any:
    """FastAPI Depends 注入 Celery App。

    用法:
        @app.post("/tasks")
        async def create_task(celery_app = Depends(get_celery)):
            ...
    """
    celery_app = getattr(request.app.state, _CELERY_STATE_KEY, None)
    if celery_app is None:
        raise RuntimeError("Celery App 未初始化，请确保 celery_lifespan 已配置")
    return celery_app


def get_redis(request: Request) -> Any:
    """FastAPI Depends 注入同步 Redis 客户端（用于分布式锁等场景）。

    用法:
        @app.post("/orders/{order_id}/lock")
        async def lock_order(order_id: str, redis = Depends(get_redis)):
            async with async_distributed_lock(redis, f"order:{order_id}"):
                ...
    """
    redis_client = getattr(request.app.state, _REDIS_STATE_KEY, None)
    if redis_client is None:
        raise RuntimeError("Redis 未初始化，请确保 celery_lifespan 已配置")
    return redis_client


# ---------------------------------------------------------------------------
# 异步任务派发
# ---------------------------------------------------------------------------


async def send_task(
    celery_app: Any,
    task_name: str,
    args: tuple | None = None,
    kwargs: dict | None = None,
    **options: Any,
) -> Any:
    """异步派发 Celery 任务，不阻塞事件循环。

    Args:
        celery_app: Celery App 实例。
        task_name: 任务全名，如 "myapp.tasks.process_order"。
        args: 位置参数。
        kwargs: 关键字参数。
        **options: 传给 send_task 的额外选项（queue, countdown 等）。

    Returns:
        AsyncResult 对象。
    """
    call = functools.partial(
        celery_app.send_task, task_name, args=args, kwargs=kwargs, **options
    )
    return await asyncio.to_thread(call)


# ---------------------------------------------------------------------------
# 任务状态轮询端点（示例路由工厂）
# ---------------------------------------------------------------------------


def create_task_status_router(prefix: str = "/tasks") -> Any:
    """创建任务状态轮询路由。

    用法:
        from fastapi import FastAPI
        app = FastAPI(lifespan=celery_lifespan)
        app.include_router(create_task_status_router())
    """
    from fastapi import APIRouter, Depends as FastAPIDepends
    router = APIRouter(prefix=prefix, tags=["tasks"])

    @router.get("/{task_id}/status")
    async def get_task_status(
        task_id: str,
        celery_app: Any = FastAPIDepends(get_celery),
    ) -> dict[str, Any]:
        """查询任务执行状态。

        返回:
            {"task_id": "...", "status": "PENDING|STARTED|SUCCESS|FAILURE", "result": ...}
        """
        return await asyncio.to_thread(_build_task_status_response, task_id, celery_app)

    return router


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：打印 FastAPI + Celery 集成模式，不启动实际服务器。"""
    print("🌐 === FastAPI + Celery 集成模式 ===\n")

    print("1️⃣  生命周期管理 (celery_lifespan):")
    print("   from fastapi import FastAPI")
    print("   from templates.fastapi_celery import celery_lifespan")
    print("   app = FastAPI(lifespan=celery_lifespan)")
    print()

    print("2️⃣  依赖注入:")
    print("   from fastapi import Depends")
    print("   from templates.fastapi_celery import get_celery, get_redis")
    print()
    print("   @app.post('/orders')")
    print("   async def create_order(celery=Depends(get_celery), redis=Depends(get_redis)):")
    print("       result = await send_task(celery, 'tasks.process_order', args=(order_id,))")
    print("       return {'task_id': result.id}")
    print()

    print("3️⃣  异步任务派发 (send_task):")
    print("   from templates.fastapi_celery import send_task")
    print("   result = await send_task(celery_app, 'tasks.process_order', args=('ORD-001',))")
    print("   # 返回 AsyncResult，不阻塞事件循环")
    print()

    print("4️⃣  任务状态轮询路由:")
    print("   from templates.fastapi_celery import create_task_status_router")
    print("   app.include_router(create_task_status_router())")
    print("   # GET /tasks/{task_id}/status → {'task_id': '...', 'status': 'SUCCESS', 'result': ...}")
    print()

    print("5️⃣  分布式锁集成:")
    print("   from templates.distributed_lock import async_distributed_lock")
    print("   @app.post('/orders/{order_id}/process')")
    print("   async def process(order_id: str, redis=Depends(get_redis)):")
    print("       async with async_distributed_lock(redis, f'order:{order_id}'):")
    print("           ...")
    print()

    # 验证导入链
    print("🔗 === 导入链验证 ===")
    print(f"  celery_lifespan: {celery_lifespan}")
    print(f"  get_celery: {get_celery}")
    print(f"  get_redis: {get_redis}")
    print(f"  send_task: {send_task}")
    print(f"  create_task_status_router: {create_task_status_router}")

    print("\n✅ FastAPI + Celery 集成模式展示完成（未启动服务器）")


if __name__ == "__main__":
    _demo()
