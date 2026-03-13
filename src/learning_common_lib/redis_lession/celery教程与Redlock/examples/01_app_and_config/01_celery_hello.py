"""
目标: 最小 Celery 应用 + 任务，演示 delay() / apply() 调用方式
关键 API: Celery(), @app.task, delay(), apply()
Python 版本: 3.11+
运行方式 (两个终端):
  终端1 (worker):  cd src/learning_common_lib/redis_lession/celery教程与Redlock && uv run celery -A examples.01_app_and_config.01_celery_hello worker --loglevel=info
  终端2 (client):  cd src/learning_common_lib/redis_lession/celery教程与Redlock && uv run python examples/01_app_and_config/01_celery_hello.py
预期现象: client 发送任务到 Redis broker，worker 接收并执行，client 通过 backend 获取结果
生产提醒: broker 密码应通过环境变量注入，勿硬编码
"""

from __future__ import annotations

import asyncio

from celery import Celery

# ── 1. 创建 Celery 应用 ──
app = Celery(
    "examples.01_app_and_config.01_celery_hello",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)

# ── 2. 定义任务 ──
@app.task
def add(x: int, y: int) -> int:
    """简单加法任务"""
    print(f"  📦 任务执行中: {x} + {y}")
    return x + y


# ── 3. 入口 ──
async def main() -> None:
    print("🚀 Celery Hello World 示例\n")

    # delay() — 最常用的快捷调用
    print("── delay() 调用 ──")
    result = await asyncio.to_thread(add.delay, 3, 7)
    print(f"  ✅ delay() 返回类型: {type(result).__name__}")
    print(f"  ✅ 结果: {await asyncio.to_thread(result.get, timeout=300)}")
    print(f"  ✅ ready: {result.ready()}")
    print()

    # apply() — 本地同步调用（始终在当前进程执行，不经过 broker）
    print("── apply() 调用 ──")
    result2 = add.apply(args=(10, 20))
    print(f"  ✅ apply() 返回类型: {type(result2).__name__}")
    print(f"  ✅ 结果: {await asyncio.to_thread(result2.get, timeout=300)}")
    print()

    # 直接函数调用（绕过 Celery 机制）
    print("── 直接调用 ──")
    plain_result = add(100, 200)
    print(f"  ✅ 直接调用返回类型: {type(plain_result).__name__}")
    print(f"  ✅ 结果: {plain_result}")
    print()

    print("💡 delay() 将任务发送到 broker，由 worker 异步处理")
    print("💡 apply() 始终在当前进程本地执行，不经过 broker")


if __name__ == "__main__":
    asyncio.run(main())
