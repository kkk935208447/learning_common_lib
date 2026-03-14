"""
目标: 演示手动重试机制与异常处理策略 (Manual Retry Mechanisms & Exception Handling)
关键概念:
  - 手动重试控制：通过 self.retry() 实现条件重试和退避策略
  - 异常分类处理：区分可重试异常和不可重试异常
  - 重试限制机制：max_retries 防止无限重试，MaxRetriesExceededError 处理最终失败
关键 API: self.retry(), max_retries, MaxRetriesExceededError, countdown
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/06_error_handling
运行方式:
  Worker: celery -A examples.06_error_handling.01_retry_basics worker -l info
    (观察重试过程和异常处理日志)
  Client: python examples/06_error_handling/01_retry_basics.py
    (触发各种异常场景并观察重试行为)
预期现象:
  - Worker 显示重试次数递增和 countdown 延迟
  - 可重试异常触发重试，不可重试异常直接失败
  - 达到 max_retries 后抛出 MaxRetriesExceededError
生产提醒:
  - 重试 countdown 建议使用指数退避算法，避免服务雪崩
  - max_retries 不宜过大，防止长时间占用 worker 资源
技术要点:
  - self.retry() 会重新入队任务，当前执行立即终止
  - countdown 参数控制重试延迟，可实现退避策略
  - bind=True 是使用 self.retry() 的前提条件
"""

from __future__ import annotations

import asyncio

from celery import Celery, Task
from celery.exceptions import MaxRetriesExceededError

# ── 1. 创建应用 ──
app = Celery(
    "examples.06_error_handling.01_retry_basics",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)


# ── 2. 模拟外部服务异常 ──
class ServiceUnavailableError(Exception):
    """模拟外部服务不可用"""
    pass


class AuthenticationError(Exception):
    """模拟认证失败 (不应重试)"""
    pass


# 模拟调用计数器
# ⚠️ 仅限教程演示：模块级字典在单 worker 进程内有效，worker 重启后计数器重置。生产环境应使用 Redis 原子计数器。
call_counts: dict[str, int] = {}


# ── 3. 基本手动重试 ──
@app.task(bind=True, max_retries=3)
def fetch_data(self: Task, url: str) -> str:
    """演示基本的 self.retry()"""
    task_key = f"fetch_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1
    attempt = call_counts[task_key]

    print(f"  📦 fetch_data 第 {attempt} 次尝试 (retries={self.request.retries})")

    if attempt <= 2:
        print(f"     ⚠️ 模拟服务不可用，准备重试...")
        try:
            raise ServiceUnavailableError(f"服务暂时不可用: {url}")
        except ServiceUnavailableError as exc:
            # self.retry() 会抛出 Retry 异常，中断当前执行
            raise self.retry(
                exc=exc,        # 保留原始异常信息
                countdown=2,    # 2秒后重试
            )

    print(f"     ✅ 第 {attempt} 次成功!")
    return f"数据来自 {url}"


# ── 4. 捕获特定异常，区分可重试与不可重试 ──
@app.task(bind=True, max_retries=3)
def smart_fetch(self: Task, url: str, fail_type: str = "service") -> str:
    """只对特定异常重试，其他异常直接失败"""
    task_key = f"smart_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1

    print(f"  📦 smart_fetch 尝试 #{call_counts[task_key]} (retries={self.request.retries})")

    try:
        if fail_type == "auth":
            raise AuthenticationError("token 过期")
        raise ServiceUnavailableError("连接超时")
    except AuthenticationError:
        # 认证错误不重试，直接抛出
        print(f"     ❌ 认证失败，不重试")
        raise
    except ServiceUnavailableError as exc:
        # 服务错误可以重试
        print(f"     ⚠️ 服务错误，重试中...")
        raise self.retry(exc=exc, countdown=1)


# ── 5. MaxRetriesExceededError 处理 ──
@app.task(bind=True, max_retries=2)
def fragile_task(self: Task, value: int) -> str:
    """演示达到最大重试次数后的处理"""
    task_key = f"fragile_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1

    print(f"  📦 fragile_task 尝试 #{call_counts[task_key]} (retries={self.request.retries})")

    try:
        raise ServiceUnavailableError("始终失败的服务")
    except ServiceUnavailableError as exc:
        try:
            raise self.retry(exc=exc, countdown=0)
        except MaxRetriesExceededError:
            # 达到最大重试次数，执行降级逻辑
            print(f"     🔥 达到最大重试次数 ({self.max_retries})，执行降级")
            return f"降级结果: 使用缓存值 {value * 10}"


# ── 6. 自定义重试延迟 (指数退避) ──
@app.task(bind=True, max_retries=4)
def exponential_retry(self: Task) -> str:
    """手动实现指数退避"""
    task_key = f"exp_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1

    retries = self.request.retries
    # 指数退避: 2^retries 秒 (1, 2, 4, 8...)
    backoff = 2 ** retries

    print(f"  📦 exponential_retry 尝试 #{call_counts[task_key]} "
          f"(retries={retries}, 下次延迟={backoff}s)")

    if call_counts[task_key] <= 3:
        try:
            raise ServiceUnavailableError("仍然不可用")
        except ServiceUnavailableError as exc:
            raise self.retry(exc=exc, countdown=backoff)

    print(f"     ✅ 终于成功!")
    return "指数退避后成功"


# ── 7. 入口 ──
async def main() -> None:
    print("🚀 手动重试 (self.retry) 示例\n")
    print("💡 重试在 worker 侧执行，客户端通过轮询 result.state 观察状态变化\n")

    # 基本重试
    print("── 基本 self.retry() ──")
    r1 = await asyncio.to_thread(fetch_data.delay, "https://api.example.com")
    print(f"  task_id: {r1.id}")
    # Poll until done
    result = await asyncio.to_thread(r1.get, timeout=30, propagate=False)
    if r1.successful():
        print(f"  ✅ 最终成功: {result}")
    else:
        print(f"  ❌ 最终失败: {result}")
    print()

    # 区分异常类型
    print("── 区分可重试与不可重试异常 ──")
    print("  🔸 认证错误 (不重试):")
    r2 = await asyncio.to_thread(smart_fetch.delay, "https://api.example.com", "auth")
    result2 = await asyncio.to_thread(r2.get, timeout=30, propagate=False)
    print(f"  ✅ 认证错误直接失败: {type(result2).__name__}: {result2}")
    print()

    # MaxRetriesExceededError 降级
    print("── MaxRetriesExceededError 降级处理 ──")
    r3 = await asyncio.to_thread(fragile_task.delay, 42)
    result3 = await asyncio.to_thread(r3.get, timeout=30, propagate=False)
    print(f"  ✅ 降级结果: {result3}")
    print()

    # 指数退避
    print("── 手动指数退避 ──")
    r4 = await asyncio.to_thread(exponential_retry.delay)
    result4 = await asyncio.to_thread(r4.get, timeout=60, propagate=False)
    if r4.successful():
        print(f"  ✅ 最终结果: {result4}")
    else:
        print(f"  ❌ 最终失败: {result4}")
    print()

    # 重试次数说明
    print("── self.request.retries 说明 ──")
    print("  📋 retries=0 表示首次执行")
    print("  📋 retries=1 表示第一次重试 (第二次执行)")
    print("  📋 max_retries=3 意味着最多执行 4 次 (1次原始 + 3次重试)")
    print()
    print("💡 只对瞬时错误重试 (网络超时、服务不可用)，永久错误 (认证失败) 不要重试")
    print("💡 生产中务必使用指数退避，避免重试风暴压垮下游服务")
    print("💡 重试过程在 worker 终端可见，客户端只看到最终结果")


if __name__ == "__main__":
    asyncio.run(main())
