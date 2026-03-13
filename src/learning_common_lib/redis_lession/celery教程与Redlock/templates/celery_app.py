"""
解决什么问题: 提供 Celery App 工厂函数和单例管理，避免多处重复创建 App 实例
输入输出约定: create_celery_app() 返回 Celery 实例；get_celery_app() 返回模块级单例；
    async_delay / async_apply 是异步包装，在 asyncio 事件循环中安全调用 Celery 同步 API
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
        name: App 名称，通常用项目名。
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


def init_celery_app(
    name: str = "worker",
    config: type | None = None,
    autodiscover: list[str] | None = None,
) -> Celery:
    """初始化模块级单例，幂等调用（重复调用返回已有实例）。"""
    global _app
    if _app is None:
        _app = create_celery_app(name, config, autodiscover)
    return _app


def get_celery_app() -> Celery:
    """获取模块级单例，未初始化时抛出 RuntimeError。"""
    if _app is None:
        raise RuntimeError(
            "Celery App 未初始化，请先调用 init_celery_app() 或 create_celery_app()"
        )
    return _app


# ---------------------------------------------------------------------------
# 异步包装 — 在 asyncio 事件循环中安全调用 Celery 同步 API
# ---------------------------------------------------------------------------


async def async_delay(task: Any, *args: Any, **kwargs: Any) -> Any:
    """异步版 task.delay()，通过 asyncio.to_thread 避免阻塞事件循环。"""
    return await asyncio.to_thread(functools.partial(task.delay, *args, **kwargs))


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
    """演示：用 CeleryConfig 创建 App，定义任务并验证 App 创建成功。

    注意: 实际执行任务需要启动 Celery Worker 和 Redis Broker。
    """
    # 1. 创建 App（使用真实 Redis 配置）
    app = create_celery_app(name="demo", config=CeleryConfig)
    print(f"🏭 创建 Celery App: {app.main}")
    print(f"  broker_url: {app.conf.broker_url}")
    print(f"  result_backend: {app.conf.result_backend}")

    # 2. 定义一个简单任务
    @app.task(name="demo.add")
    def add(x: int, y: int) -> int:
        return x + y

    print(f"\n📦 注册任务: {add.name}")

    # 3. 演示单例模式
    print("\n🔗 === 单例模式 ===")
    singleton = init_celery_app(name="singleton_demo", config=CeleryConfig)
    same = get_celery_app()
    print(f"  init_celery_app() is get_celery_app(): {singleton is same}")

    print("\n💡 要执行任务，请先启动 Redis，然后运行 Celery Worker:")
    print("   celery -A celery_app worker --loglevel=info")

    print("\n✅ Celery App 工厂演示完成")


if __name__ == "__main__":
    _demo()
