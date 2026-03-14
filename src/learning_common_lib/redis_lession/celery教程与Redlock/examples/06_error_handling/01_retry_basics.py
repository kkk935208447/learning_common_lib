"""
目标: 用 async task 演示手动重试机制与异常处理策略 (Manual Retry with async tasks)
关键概念:
  - worker 侧任务已经切到 `custom aio pool + async def task`
  - `self.retry()`、`max_retries`、`countdown` 的语义不变
  - 只对瞬时错误重试，永久错误直接失败
关键 API: self.retry(), max_retries, MaxRetriesExceededError, countdown
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/06_error_handling
运行方式:
  Worker:
    CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool' \
    celery -A examples.06_error_handling.01_retry_basics worker -l info -P custom -Q aio_retries -c 20
  Client:
    python examples/06_error_handling/01_retry_basics.py
预期现象:
  - Worker 显示重试次数递增和 countdown 延迟
  - 可重试异常触发重试，不可重试异常直接失败
  - 达到 max_retries 后抛出 MaxRetriesExceededError
"""

from __future__ import annotations

import asyncio

from celery import Celery, Task
from celery.exceptions import MaxRetriesExceededError

MODULE = "examples.06_error_handling.01_retry_basics"

app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.task_default_queue = "aio_retries"


class ServiceUnavailableError(Exception):
    """模拟外部服务不可用"""


class AuthenticationError(Exception):
    """模拟认证失败 (不应重试)"""


call_counts: dict[str, int] = {}


@app.task(bind=True, max_retries=3, name=f"{MODULE}.fetch_data")
async def fetch_data(self: Task, url: str) -> str:
    task_key = f"fetch_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1
    attempt = call_counts[task_key]

    print(f"  📦 fetch_data 第 {attempt} 次尝试 (retries={self.request.retries})")
    await asyncio.sleep(0.1)

    if attempt <= 2:
        print("     ⚠️ 模拟服务不可用，准备重试...")
        try:
            raise ServiceUnavailableError(f"服务暂时不可用: {url}")
        except ServiceUnavailableError as exc:
            raise self.retry(exc=exc, countdown=2)

    print(f"     ✅ 第 {attempt} 次成功!")
    return f"数据来自 {url}"


@app.task(bind=True, max_retries=3, name=f"{MODULE}.smart_fetch")
async def smart_fetch(self: Task, url: str, fail_type: str = "service") -> str:
    task_key = f"smart_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1

    print(f"  📦 smart_fetch 尝试 #{call_counts[task_key]} (retries={self.request.retries})")
    await asyncio.sleep(0.1)

    try:
        if fail_type == "auth":
            raise AuthenticationError("token 过期")
        raise ServiceUnavailableError("连接超时")
    except AuthenticationError:
        print("     ❌ 认证失败，不重试")
        raise
    except ServiceUnavailableError as exc:
        print("     ⚠️ 服务错误，重试中...")
        raise self.retry(exc=exc, countdown=1)


@app.task(bind=True, max_retries=2, name=f"{MODULE}.fragile_task")
async def fragile_task(self: Task, value: int) -> str:
    task_key = f"fragile_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1

    print(f"  📦 fragile_task 尝试 #{call_counts[task_key]} (retries={self.request.retries})")
    await asyncio.sleep(0.05)

    try:
        raise ServiceUnavailableError("始终失败的服务")
    except ServiceUnavailableError as exc:
        try:
            raise self.retry(exc=exc, countdown=0)
        except MaxRetriesExceededError:
            print(f"     🔥 达到最大重试次数 ({self.max_retries})，执行降级")
            return f"降级结果: 使用缓存值 {value * 10}"


@app.task(bind=True, max_retries=4, name=f"{MODULE}.exponential_retry")
async def exponential_retry(self: Task) -> str:
    task_key = f"exp_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1

    retries = self.request.retries
    backoff = 2 ** retries

    print(
        f"  📦 exponential_retry 尝试 #{call_counts[task_key]} "
        f"(retries={retries}, 下次延迟={backoff}s)"
    )
    await asyncio.sleep(0.05)

    if call_counts[task_key] <= 3:
        try:
            raise ServiceUnavailableError("仍然不可用")
        except ServiceUnavailableError as exc:
            raise self.retry(exc=exc, countdown=backoff)

    print("     ✅ 终于成功!")
    return "指数退避后成功"


async def main() -> None:
    print("🚀 手动重试 (self.retry) 示例（async task）\n")
    print("💡 worker 侧已经切到 async-first；producer/result 侧仍通过 to_thread 与 Celery 客户端交互\n")

    print("── 基本 self.retry() ──")
    r1 = await asyncio.to_thread(fetch_data.delay, "https://api.example.com")
    result = await asyncio.to_thread(r1.get, timeout=30, propagate=False)
    print(f"  {'✅ 最终成功' if r1.successful() else '❌ 最终失败'}: {result}")
    print()

    print("── 区分可重试与不可重试异常 ──")
    r2 = await asyncio.to_thread(smart_fetch.delay, "https://api.example.com", "auth")
    result2 = await asyncio.to_thread(r2.get, timeout=30, propagate=False)
    print(f"  ✅ 认证错误直接失败: {type(result2).__name__}: {result2}")
    print()

    print("── MaxRetriesExceededError 降级处理 ──")
    r3 = await asyncio.to_thread(fragile_task.delay, 42)
    result3 = await asyncio.to_thread(r3.get, timeout=30, propagate=False)
    print(f"  ✅ 降级结果: {result3}")
    print()

    print("── 手动指数退避 ──")
    r4 = await asyncio.to_thread(exponential_retry.delay)
    result4 = await asyncio.to_thread(r4.get, timeout=60, propagate=False)
    print(f"  {'✅ 最终结果' if r4.successful() else '❌ 最终失败'}: {result4}")
    print()

    print("── self.request.retries 说明 ──")
    print("  📋 retries=0 表示首次执行")
    print("  📋 retries=1 表示第一次重试 (第二次执行)")
    print("  📋 max_retries=3 意味着最多执行 4 次 (1次原始 + 3次重试)")
    print()
    print("💡 async-first 只改变 worker 执行模型，不改变 self.retry() 的语义")
    print("💡 只对瞬时错误重试 (网络超时、服务不可用)，永久错误 (认证失败) 不要重试")
    print("💡 生产中务必使用指数退避，避免重试风暴压垮下游服务")


if __name__ == "__main__":
    asyncio.run(main())
