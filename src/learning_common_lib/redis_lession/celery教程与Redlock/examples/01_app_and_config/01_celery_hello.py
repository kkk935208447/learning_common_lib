"""
目标: 演示 Celery 任务的基本定义与调用机制 (Task Definition & Invocation)
关键概念:
  - 任务装饰器 (@app.task) 将普通函数转换为 Celery 任务
  - 异步调用 (delay/apply_async) vs 同步调用 (apply/直接调用)
  - AsyncResult 对象管理任务状态和结果获取
关键 API: @app.task, task.delay(), task.apply_async(), result.get(), result.ready()
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/01_app_and_config
运行方式:
  Worker: celery -A examples.01_app_and_config.01_celery_hello worker -l info
    (启动工作进程监听任务队列，-l info 显示详细日志)
  Client: python examples/01_app_and_config/01_celery_hello.py
    (发送任务到队列并获取结果)
预期现象:
  - Worker 控制台显示任务接收和执行日志
  - Client 显示 PENDING → SUCCESS 状态变化
  - Redis 中可观察到任务状态数据 (key: celery-task-meta-*)
生产提醒:
  - 避免在 Web 请求处理中调用 result.get()，会阻塞整个请求响应
  - 生产环境应设置 result.get(timeout=N) 避免无限等待
  - 考虑使用 result.ready() 轮询或 WebSocket 推送结果
技术要点:
  - delay() 是 apply_async() 的快捷方式，等价于 apply_async(args, kwargs)
  - apply() 始终在当前进程执行，不经过 broker，用于测试
  - AsyncResult.get() 会阻塞直到任务完成或超时
注意: 手动运行多个示例前建议清理 Redis: redis-cli -a 123456 -n 0 FLUSHDB
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
    print(f"  ✅ ready (任务提交后): {result.ready()}")

    # 短暂等待以观察状态变化
    await asyncio.sleep(0.1)
    print(f"  ✅ ready (等待后): {result.ready()}")

    print(f"  ✅ 结果: {await asyncio.to_thread(result.get, timeout=300)}")
    print(f"  ✅ ready (获取结果后): {result.ready()}")
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
