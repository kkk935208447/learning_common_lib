"""
目标: 用 async task 演示自动重试与退避策略 (Autoretry with async tasks)
关键概念:
  - `autoretry_for` 依旧可用于 async task
  - `retry_backoff` / `retry_jitter` 的行为与同步 task 时代一致
  - 回调类 Task 仍然有用，但任务实现本身可切到 async def
关键 API: autoretry_for, retry_backoff, retry_jitter, on_failure, retry_backoff_max
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/06_error_handling
运行方式:
  Worker:
    CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool' \
    celery -A examples.06_error_handling.02_autoretry worker -l info -P custom -Q aio_autoretry -c 20
  Client:
    python examples/06_error_handling/02_autoretry.py
预期现象:
  - autoretry_for 异常自动重试，其他异常直接失败
  - retry_backoff=True 时重试间隔呈指数增长
  - retry_jitter=True 时每次重试间隔有随机抖动
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery, Task

MODULE = "examples.06_error_handling.02_autoretry"

app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.task_default_queue = "aio_autoretry"


class TransientError(Exception):
    """瞬时错误，可重试"""


class PermanentError(Exception):
    """永久错误，不应重试"""


call_counts: dict[str, int] = {}


@app.task(
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=3,
    retry_backoff=False,
    default_retry_delay=1,
    name=f"{MODULE}.basic_autoretry",
)
async def basic_autoretry(self: Task, succeed_on: int = 3) -> str:
    task_key = f"basic_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1
    attempt = call_counts[task_key]

    print(f"  📦 basic_autoretry 尝试 #{attempt} (retries={self.request.retries})")
    await asyncio.sleep(0.1)

    if attempt < succeed_on:
        raise TransientError(f"第 {attempt} 次瞬时错误")

    return f"第 {attempt} 次成功"


@app.task(
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=False,
    name=f"{MODULE}.backoff_task",
)
async def backoff_task(self: Task) -> str:
    task_key = f"backoff_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1
    attempt = call_counts[task_key]

    retries = self.request.retries
    theoretical_delay = min(2 ** retries, 60)
    print(
        f"  📦 backoff_task 尝试 #{attempt} "
        f"(retries={retries}, 理论延迟={theoretical_delay}s)"
    )
    await asyncio.sleep(0.05)

    if attempt <= 4:
        raise TransientError("服务不可用")

    return "退避后成功"


@app.task(
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
    name=f"{MODULE}.jitter_task",
)
async def jitter_task(self: Task) -> str:
    task_key = f"jitter_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1
    attempt = call_counts[task_key]

    print(f"  📦 jitter_task 尝试 #{attempt} (retries={self.request.retries})")
    await asyncio.sleep(0.05)

    if attempt <= 2:
        raise TransientError("需要抖动重试")

    return "抖动重试成功"


class MonitoredTask(Task):
    """带监控回调的任务基类"""

    def on_failure(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        print("  🔔 [on_failure] 任务最终失败!")
        print(f"     task_id: {task_id}")
        print(f"     异常类型: {type(exc).__name__}")
        print(f"     异常信息: {exc}")
        print(f"     参数: args={args}, kwargs={kwargs}")

    def on_retry(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        print(f"  🔄 [on_retry] 任务重试中: {type(exc).__name__}: {exc}")

    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        print(f"  🎉 [on_success] 任务成功: {retval}")


@app.task(
    base=MonitoredTask,
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=2,
    retry_backoff=True,
    name=f"{MODULE}.monitored_task",
)
async def monitored_task(self: Task, should_fail: bool = True) -> str:
    task_key = f"monitored_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1

    print(f"  📦 monitored_task 尝试 #{call_counts[task_key]}")
    await asyncio.sleep(0.05)

    if should_fail:
        raise TransientError("持续失败")

    return "监控任务成功"


@app.task(
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=3,
    retry_backoff=True,
    name=f"{MODULE}.selective_retry",
)
async def selective_retry(self: Task, error_type: str = "transient") -> str:
    task_key = f"selective_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1

    print(f"  📦 selective_retry 尝试 #{call_counts[task_key]} (error={error_type})")
    await asyncio.sleep(0.05)

    if error_type == "permanent":
        raise PermanentError("永久错误，不会被 autoretry 捕获")
    raise TransientError("瞬时错误，会被 autoretry 捕获")


async def main() -> None:
    print("🚀 自动重试 (autoretry) 示例（async task）\n")
    print("💡 producer 侧仍通过 to_thread 与 Celery 客户端交互，worker 侧已经切到 async-first\n")

    print("── 基本 autoretry_for ──")
    r1 = await asyncio.to_thread(basic_autoretry.delay, 3)
    result1 = await asyncio.to_thread(r1.get, timeout=30, propagate=False)
    print(f"  {'✅ 结果' if await asyncio.to_thread(r1.successful) else '❌ 失败'}: {result1}")
    print()

    print("── retry_backoff 指数退避 ──")
    r2 = await asyncio.to_thread(backoff_task.delay)
    result2 = await asyncio.to_thread(r2.get, timeout=120, propagate=False)
    print(f"  {'✅ 结果' if await asyncio.to_thread(r2.successful) else '❌ 失败'}: {result2}")
    print()

    print("── retry_jitter 抖动 ──")
    r3 = await asyncio.to_thread(jitter_task.delay)
    result3 = await asyncio.to_thread(r3.get, timeout=30, propagate=False)
    print(f"  {'✅ 结果' if await asyncio.to_thread(r3.successful) else '❌ 失败'}: {result3}")
    print()

    print("── on_failure / on_retry / on_success 回调 ──")
    r4 = await asyncio.to_thread(monitored_task.delay, True)
    result4 = await asyncio.to_thread(r4.get, timeout=30, propagate=False)
    if await asyncio.to_thread(r4.failed):
        print(f"  ✅ 任务在 max_retries 次后最终失败: {type(result4).__name__}")
    print()

    print("── autoretry_for 只捕获指定异常 ──")
    r5 = await asyncio.to_thread(selective_retry.delay, "permanent")
    result5 = await asyncio.to_thread(r5.get, timeout=30, propagate=False)
    if await asyncio.to_thread(r5.failed):
        print(f"  ✅ PermanentError 直接失败 (未重试): {type(result5).__name__}: {result5}")
    print()

    print("── autoretry 参数一览 ──")
    params: list[tuple[str, str]] = [
        ("autoretry_for", "元组，指定哪些异常触发自动重试"),
        ("max_retries", "最大重试次数 (默认 3)"),
        ("retry_backoff", "True 启用指数退避，或指定基数 (如 2)"),
        ("retry_backoff_max", "退避上限秒数 (默认 600)"),
        ("retry_jitter", "True 在退避上添加随机抖动"),
        ("dont_autoretry_for", "元组，排除特定异常不自动重试"),
    ]
    for param, desc in params:
        print(f"  📋 {param:.<25} {desc}")
    print()

    print("💡 autoretry_for 在 async task 中同样成立")
    print("💡 复杂场景 (不同异常不同策略) 仍需手动 self.retry()")
    print("💡 生产必备: retry_backoff=True + retry_jitter=True + 合理的 retry_backoff_max")


if __name__ == "__main__":
    asyncio.run(main())
