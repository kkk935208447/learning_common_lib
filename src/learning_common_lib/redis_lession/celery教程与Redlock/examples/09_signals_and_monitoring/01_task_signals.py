"""
目标: Task 信号系统 — 监听任务生命周期事件
关键 API: task_prerun, task_postrun, task_success, task_failure, before_task_publish
Python 版本: 3.11+
运行命令:
  终端 1 (启动 Worker):
    celery -A examples.09_signals_and_monitoring.01_task_signals worker -l info -P solo
  终端 2 (运行示例):
    uv run python examples/09_signals_and_monitoring/01_task_signals.py
  (从 src/learning_common_lib/redis_lession/celery教程与Redlock 目录)
预期现象: Worker 终端打印信号触发顺序，客户端终端显示任务结果
生产提醒: 信号处理器应轻量快速，避免阻塞
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery
from celery.signals import (
    after_task_publish,
    before_task_publish,
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    task_success,
)

# ── 1. 创建 Celery 应用 ──
app = Celery(
    "examples.09_signals_and_monitoring.01_task_signals",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)


# ── 2. 注册信号处理器 ──
@before_task_publish.connect
def on_before_publish(sender: str | None = None, headers: dict | None = None,
                      body: Any = None, **kwargs: Any) -> None:
    """任务发布前 (客户端进程触发)"""
    msg = f"  📡 [before_task_publish] 任务即将发布: {sender}"
    print(msg)


@after_task_publish.connect
def on_after_publish(sender: str | None = None, headers: dict | None = None,
                     body: Any = None, **kwargs: Any) -> None:
    """任务发布后 (客户端进程触发)"""
    msg = f"  📡 [after_task_publish] 任务已发布: {sender}"
    print(msg)


@task_prerun.connect
def on_task_prerun(sender: Any = None, task_id: str | None = None,
                   args: tuple = (), kwargs: dict | None = None, **kw: Any) -> None:
    """任务执行前 (worker 进程触发)"""
    msg = f"  🟡 [task_prerun] task={sender.name}, id={task_id}, args={args}"
    print(msg)


@task_postrun.connect
def on_task_postrun(sender: Any = None, task_id: str | None = None,
                    args: tuple = (), kwargs: dict | None = None,
                    retval: Any = None, state: str | None = None, **kw: Any) -> None:
    """任务执行后 (无论成功失败, worker 进程触发)"""
    msg = f"  🔵 [task_postrun] task={sender.name}, state={state}, retval={retval}"
    print(msg)


@task_success.connect
def on_task_success(sender: Any = None, result: Any = None, **kwargs: Any) -> None:
    """任务成功 (worker 进程触发)"""
    msg = f"  🟢 [task_success] task={sender.name}, result={result}"
    print(msg)


@task_failure.connect
def on_task_failure(sender: Any = None, task_id: str | None = None,
                    exception: BaseException | None = None,
                    traceback: Any = None, **kwargs: Any) -> None:
    """任务失败 (worker 进程触发)"""
    msg = f"  🔴 [task_failure] task={sender.name}, exception={exception}"
    print(msg)


@task_retry.connect
def on_task_retry(sender: Any = None, request: Any = None,
                  reason: Any = None, **kwargs: Any) -> None:
    """任务重试 (worker 进程触发)"""
    msg = f"  🟠 [task_retry] task={sender.name}, reason={reason}"
    print(msg)


# ── 3. 定义任务 ──
@app.task
def compute(x: int, y: int) -> int:
    """正常任务"""
    result = x + y
    print(f"  ⚙️ [task_body] compute({x}, {y}) = {result}")
    return result


@app.task
def broken_task(msg: str) -> str:
    """故意失败的任务"""
    print(f"  ⚙️ [task_body] broken_task 即将抛出异常")
    raise RuntimeError(f"模拟错误: {msg}")


# ── 4. 入口 ──
async def main() -> None:
    print("🚀 Celery 信号系统示例\n")
    print("  ℹ️ 信号输出说明:")
    print("    before_task_publish / after_task_publish 在客户端进程触发（发布侧）")
    print("    其余信号在 worker 进程触发，请查看 worker 终端输出\n")

    # 成功任务
    print("── 成功任务 ──")
    r1 = await asyncio.to_thread(compute.delay, 10, 20)
    result = await asyncio.to_thread(r1.get, timeout=30)
    print(f"  ✅ 结果: {result}")
    print("  ℹ️ task_prerun → task_success → task_postrun 信号已在 worker 终端打印\n")

    # 失败任务
    print("── 失败任务 ──")
    r2 = await asyncio.to_thread(broken_task.delay, "数据库连接超时")
    error = await asyncio.to_thread(r2.get, timeout=30, propagate=False)
    print(f"  ❌ 错误: {error}")
    print("  ℹ️ task_prerun → task_failure → task_postrun 信号已在 worker 终端打印\n")

    # 信号参数速查
    print("── 信号参数速查表 ──")
    signals_info = [
        ("before_task_publish", "sender(任务名), headers, body, exchange, routing_key"),
        ("after_task_publish", "sender(任务名), headers, body, exchange, routing_key"),
        ("task_prerun", "sender(任务类), task_id, args, kwargs"),
        ("task_postrun", "sender(任务类), task_id, args, kwargs, retval, state"),
        ("task_success", "sender(任务类), result"),
        ("task_failure", "sender(任务类), task_id, exception, traceback, einfo"),
        ("task_retry", "sender(任务类), request, reason, einfo"),
    ]
    for sig_name, params in signals_info:
        print(f"  💡 {sig_name}")
        print(f"     参数: {params}")
    print()

    # 信号连接方式
    print("── 信号连接方式 ──")
    print("  💡 方式一: @signal.connect — 接收所有任务的信号")
    print("  💡 方式二: @signal.connect(sender=specific_task) — 只接收特定任务")
    print("  💡 方式三: signal.connect(handler_func) — 函数式连接")
    print()
    print("  ⚠️ before_task_publish / after_task_publish 在客户端进程触发（发布侧），其余信号在 worker 进程触发")
    print("  ⚠️ 信号处理器中不要执行耗时操作，会阻塞任务执行")


if __name__ == "__main__":
    asyncio.run(main())
