"""
解决什么问题: 提供 async-first 的 Celery App 工厂函数和单例管理，统一 custom aio pool worker 配置约定
输入输出约定: create_celery_app() 返回 Celery 实例；get_celery_app() 返回模块级单例；
    async_delay / async_apply 是 producer 侧兼容包装，在 asyncio 事件循环中安全调用 Celery 同步 API
失败策略: get_celery_app() 在未初始化时抛出 RuntimeError；async 包装透传底层异常
不适用场景: 需要多个独立 Celery App 的场景应直接使用 create_celery_app()，不依赖单例

工厂 + 单例模式:
  create_celery_app(name, config)  →  新建 App
  get_celery_app()                 →  获取模块级单例
  init_celery_app(name, config)    →  初始化单例（只调用一次）
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any

from celery import Celery

try:
    from .celery_config import CeleryConfig
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.celery_config import CeleryConfig  # type: ignore[no-redef]

CUSTOM_AIO_POOL_CLASS = "celery_aio_pool.pool:AsyncIOPool"


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def create_celery_app(
    name: str = "worker",
    config: type | None = None,
    autodiscover: list[str] | None = None,
) -> Celery:
    """创建 Celery App 实例。

    Args:
        name: App 名称。生产中建议传稳定的项目包名，如 "myproj"；
            不建议长期使用 "worker"、"demo" 这类临时名。
        config: 配置类，默认 CeleryConfig。
        autodiscover: 自动发现任务的包列表，如 ["myapp.tasks"]。
    """
    app = Celery(name)
    app.config_from_object(config or CeleryConfig)

    if autodiscover:
        app.autodiscover_tasks(autodiscover)

    return app


# ---------------------------------------------------------------------------
# 单例管理
# ---------------------------------------------------------------------------

_app: Celery | None = None
_app_init_signature: tuple[str, type, tuple[str, ...]] | None = None


def init_celery_app(
    name: str = "worker",
    config: type | None = None,
    autodiscover: list[str] | None = None,
) -> Celery:
    """初始化模块级单例，幂等调用（重复调用返回已有实例）。"""
    global _app
    global _app_init_signature

    current_signature = (
        name,
        config or CeleryConfig,
        tuple(autodiscover or ()),
    )
    if _app is None:
        _app = create_celery_app(name, config, autodiscover)
        _app_init_signature = current_signature
        return _app
    if _app_init_signature != current_signature:
        raise RuntimeError(
            "Celery App 已按不同参数初始化，"
            "请保持 name/config/autodiscover 一致，或直接使用 create_celery_app() 创建独立实例"
        )
    return _app


def get_celery_app() -> Celery:
    """获取模块级单例，未初始化时抛出 RuntimeError。"""
    if _app is None:
        raise RuntimeError(
            "Celery App 未初始化，请先调用 init_celery_app() 或 create_celery_app()"
        )
    return _app


# ---------------------------------------------------------------------------
# Producer 侧异步包装 — 在 asyncio 事件循环中安全调用 Celery 同步 API
# ---------------------------------------------------------------------------


async def async_delay(task: Any, *args: Any, **kwargs: Any) -> Any:
    """异步版 task.delay()，通过 asyncio.to_thread 避免阻塞事件循环。"""
    return await asyncio.to_thread(task.delay, *args, **kwargs)


async def async_apply(
    task: Any,
    args: tuple | None = None,
    kwargs: dict | None = None,
    **options: Any,
) -> Any:
    """异步版 task.apply_async()，通过 asyncio.to_thread 避免阻塞事件循环。"""
    call = functools.partial(
        task.apply_async, args=args, kwargs=kwargs, **options
    )
    return await asyncio.to_thread(call)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：用 async-first CeleryConfig 创建 App，注册 async task 并打印 worker 启动方式。

    注意: 实际执行任务需要启动 Redis 和 custom aio pool worker。
    """
    app = create_celery_app(name="demo", config=CeleryConfig)
    print(f"🏭 创建 Celery App: {app.main}")
    print(f"  broker_url: {app.conf.broker_url}")
    print(f"  result_backend: {app.conf.result_backend}")
    print(f"  task_default_queue: {app.conf.task_default_queue}")
    print(f"  worker_pool: {app.conf.worker_pool}")
    print(f"  custom_worker_pool: {app.conf.custom_worker_pool}")

    @app.task(name="demo.fetch_order")
    async def fetch_order(order_id: str) -> dict[str, str]:
        await asyncio.sleep(0.1)
        return {"order_id": order_id, "status": "ready"}

    print(f"\n📦 注册任务: {fetch_order.name}")
    print("  task 形态: async def")

    print("\n🔗 === 单例模式 ===")
    singleton = init_celery_app(name="singleton_demo", config=CeleryConfig)
    same = get_celery_app()
    print(f"  init_celery_app() is get_celery_app(): {singleton is same}")

    print("\n💡 async-first worker 启动方式:")
    print(
        f"   CELERY_CUSTOM_WORKER_POOL='{CUSTOM_AIO_POOL_CLASS}' "
        "celery -A myproj.celery_app:app worker -P custom -Q aio_jobs --loglevel=info -c 20"
    )
    print("   # producer 侧仍可通过 async_delay/async_apply 包装 Celery 同步客户端 API")

    print("\n✅ async-first Celery App 工厂演示完成")


if __name__ == "__main__":
    _demo()
