"""
目标: 演示自动重试机制与退避策略 (Automatic Retry Mechanisms & Backoff Strategies)
关键概念:
  - 自动重试配置：autoretry_for 指定可重试异常类型，无需手动调用 retry()
  - 退避策略：retry_backoff 实现指数退避，retry_jitter 添加随机抖动
  - 失败回调：on_failure 钩子处理最终失败场景
关键 API: autoretry_for, retry_backoff, retry_jitter, on_failure, retry_backoff_max
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/06_error_handling
运行方式:
  Worker: celery -A examples.06_error_handling.02_autoretry worker -l info
    (观察自动重试的指数退避和抖动过程)
  Client: python examples/06_error_handling/02_autoretry.py
    (触发不同异常类型并观察自动重试行为)
预期现象:
  - autoretry_for 异常自动重试，其他异常直接失败
  - retry_backoff=True 时重试间隔呈指数增长
  - retry_jitter=True 时每次重试间隔有随机抖动
生产提醒:
  - autoretry_for 只捕获指定异常，务必明确列出所有可重试异常
  - retry_backoff_max 防止退避延迟过长，建议设置合理上限
技术要点:
  - autoretry_for 比手动 retry() 更简洁，适合标准重试场景
  - 指数退避算法：delay = base * (2 ** retry_count)
  - 抖动机制防止多个任务同时重试造成的雷群效应
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery, Task

# ── 1. 创建应用 ──
app = Celery(
    "examples.06_error_handling.02_autoretry",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)


# ── 2. 自定义异常 ──
class TransientError(Exception):
    """瞬时错误，可重试"""
    pass


class PermanentError(Exception):
    """永久错误，不应重试"""
    pass


# 调用计数器
# ⚠️ 仅限教程演示：模块级字典在单 worker 进程内有效，worker 重启后计数器重置。生产环境应使用 Redis 原子计数器。
call_counts: dict[str, int] = {}


# ── 3. 基本 autoretry_for ──
@app.task(
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=3,
    retry_backoff=False,  # 先不用退避，看基本行为
    default_retry_delay=1,  # 显式缩短默认重试间隔，避免 Celery 默认 180s 干扰示例
)
def basic_autoretry(self: Task, succeed_on: int = 3) -> str:
    """autoretry_for 自动捕获指定异常并重试"""
    task_key = f"basic_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1
    attempt = call_counts[task_key]

    print(f"  📦 basic_autoretry 尝试 #{attempt} (retries={self.request.retries})")

    if attempt < succeed_on:
        raise TransientError(f"第 {attempt} 次瞬时错误")

    return f"第 {attempt} 次成功"


# ── 4. retry_backoff 指数退避 ──
@app.task(
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=5,
    retry_backoff=True,         # 启用指数退避: 1s, 2s, 4s, 8s...
    retry_backoff_max=60,       # 最大退避时间 60 秒
    retry_jitter=False,         # 先关闭抖动，看纯指数退避
)
def backoff_task(self: Task) -> str:
    """指数退避: 延迟 = min(2^retries, retry_backoff_max)"""
    task_key = f"backoff_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1
    attempt = call_counts[task_key]

    retries = self.request.retries
    # 计算理论退避时间
    theoretical_delay = min(2 ** retries, 60)
    print(f"  📦 backoff_task 尝试 #{attempt} "
          f"(retries={retries}, 理论延迟={theoretical_delay}s)")

    if attempt <= 4:
        raise TransientError("服务不可用")

    return "退避后成功"


# ── 5. retry_jitter 抖动 ──
@app.task(
    bind=True,
    autoretry_for=(TransientError,),
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,          # 在退避时间上添加随机抖动
)
def jitter_task(self: Task) -> str:
    """retry_jitter=True 在退避基础上添加随机偏移，避免惊群效应"""
    task_key = f"jitter_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1
    attempt = call_counts[task_key]

    print(f"  📦 jitter_task 尝试 #{attempt} (retries={self.request.retries})")

    if attempt <= 2:
        raise TransientError("需要抖动重试")

    return "抖动重试成功"


# ── 6. on_failure 回调 ──
class MonitoredTask(Task):
    """带监控回调的任务基类"""

    def on_failure(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        print(f"  🔔 [on_failure] 任务最终失败!")
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
)
def monitored_task(self: Task, should_fail: bool = True) -> str:
    """结合 on_failure 回调的自动重试任务"""
    task_key = f"monitored_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1

    print(f"  📦 monitored_task 尝试 #{call_counts[task_key]}")

    if should_fail:
        raise TransientError("持续失败")

    return "监控任务成功"


# ── 7. 组合: autoretry + 自定义异常层级 ──
@app.task(
    bind=True,
    autoretry_for=(TransientError,),  # 只自动重试 TransientError
    max_retries=3,
    retry_backoff=True,
)
def selective_retry(self: Task, error_type: str = "transient") -> str:
    """autoretry_for 只捕获指定异常，其他异常直接失败"""
    task_key = f"selective_{self.request.id}"
    call_counts.setdefault(task_key, 0)
    call_counts[task_key] += 1

    print(f"  📦 selective_retry 尝试 #{call_counts[task_key]} (error={error_type})")

    if error_type == "permanent":
        raise PermanentError("永久错误，不会被 autoretry 捕获")
    raise TransientError("瞬时错误，会被 autoretry 捕获")


# ── 8. 入口 ──
async def main() -> None:
    print("🚀 自动重试 (autoretry) 示例\n")
    print("💡 autoretry 在 worker 侧自动触发，客户端通过轮询观察最终结果\n")

    # 基本 autoretry
    print("── 基本 autoretry_for ──")
    r1 = await asyncio.to_thread(basic_autoretry.delay, 3)
    result1 = await asyncio.to_thread(r1.get, timeout=30, propagate=False)
    if r1.successful():
        print(f"  ✅ 结果: {result1}")
    else:
        print(f"  ❌ 失败: {result1}")
    print()

    # 指数退避
    print("── retry_backoff 指数退避 ──")
    print("  💡 退避过程在 worker 终端可见: 1s, 2s, 4s, 8s...")
    r2 = await asyncio.to_thread(backoff_task.delay)
    result2 = await asyncio.to_thread(r2.get, timeout=120, propagate=False)
    if r2.successful():
        print(f"  ✅ 结果: {result2}")
    else:
        print(f"  ❌ 失败: {result2}")
    print()

    # 抖动
    print("── retry_jitter 抖动 ──")
    r3 = await asyncio.to_thread(jitter_task.delay)
    result3 = await asyncio.to_thread(r3.get, timeout=30, propagate=False)
    if r3.successful():
        print(f"  ✅ 结果: {result3}")
    else:
        print(f"  ❌ 失败: {result3}")
    print()

    # on_failure 回调
    print("── on_failure / on_retry / on_success 回调 ──")
    print("  💡 回调在 worker 进程中触发，查看 worker 终端输出")
    print("  🔸 最终失败的任务:")
    r4 = await asyncio.to_thread(monitored_task.delay, True)
    result4 = await asyncio.to_thread(r4.get, timeout=30, propagate=False)
    if r4.failed():
        print(f"  ✅ 任务在 max_retries 次后最终失败: {type(result4).__name__}")
    print()

    # autoretry 只捕获指定异常
    print("── autoretry_for 只捕获指定异常 ──")
    print("  🔸 PermanentError 不会被 autoretry 捕获:")
    r5 = await asyncio.to_thread(selective_retry.delay, "permanent")
    result5 = await asyncio.to_thread(r5.get, timeout=30, propagate=False)
    if r5.failed():
        print(f"  ✅ PermanentError 直接失败 (未重试): {type(result5).__name__}: {result5}")
    print()

    # 参数一览
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

    print("💡 autoretry_for 比手动 self.retry() 更简洁，适合统一的重试策略")
    print("💡 复杂场景 (不同异常不同策略) 仍需手动 self.retry()")
    print("💡 生产必备: retry_backoff=True + retry_jitter=True + 合理的 retry_backoff_max")


if __name__ == "__main__":
    asyncio.run(main())
