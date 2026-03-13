"""
目标: 演示 AsyncResult 状态机与结果管理 (AsyncResult State Machine & Result Management)
关键概念:
  - 任务状态机：PENDING → SUCCESS/FAILURE/RETRY，状态转换不可逆
  - AsyncResult 对象：任务结果的代理，提供状态查询和结果获取接口
  - 结果存储机制：backend 存储任务状态和返回值，支持跨进程访问
关键 API: AsyncResult, .get(), .ready(), .successful(), .failed(), .state, .info, .forget()
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/04_result_backend
运行方式:
  Worker: celery -A examples.04_result_backend.01_async_result worker -l info
    (worker 执行任务并更新状态到 backend)
  Client: python examples/04_result_backend/01_async_result.py
    (创建任务并通过 AsyncResult 监控状态变化)
预期现象:
  - 任务状态从 PENDING 转换到 SUCCESS/FAILURE
  - ready() 方法反映任务完成状态，successful()/failed() 反映执行结果
  - Redis backend 中存储任务元数据 (key: celery-task-meta-*)
生产提醒:
  - .get() 会阻塞当前线程直到任务完成，生产环境必须设置 timeout 参数
  - 频繁轮询 .state 会增加 backend 负载，建议使用事件机制或适当间隔
技术要点:
  - ready() 检查任务是否完成，不区分成功失败
  - successful() 仅在任务成功完成时返回 True
  - .info 在任务失败时包含异常信息，成功时包含返回值
  - forget() 从 backend 删除任务结果，释放存储空间
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery
from celery.result import AsyncResult

# ── 1. 创建应用 ──
app = Celery(
    "examples.04_result_backend.01_async_result",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.update(
    task_track_started=True,  # 启用 STARTED 状态追踪
)


# ── 2. 成功任务 ──
@app.task(bind=True)
def compute(self, x: int, y: int) -> int:
    print(f"  📦 compute({x}, {y}) 执行中...")
    return x + y


# ── 3. 失败任务 ──
@app.task
def fail_task() -> None:
    raise ValueError("故意抛出的错误")


# ── 4. 辅助函数：打印 AsyncResult 状态 ──
def print_result_info(result: AsyncResult, label: str) -> None:
    print(f"  {'─' * 40}")
    print(f"  📋 {label}")
    print(f"  task_id:     {result.id}")
    print(f"  state:       {result.state}")
    print(f"  ready:       {result.ready()}")
    print(f"  successful:  {result.successful()}")
    print(f"  failed:      {result.failed()}")
    print(f"  info:        {result.info!r}")


# ── 5. 入口 ──
async def main() -> None:
    print("🚀 AsyncResult 状态机示例\n")

    # ── 状态流转: PENDING → STARTED → SUCCESS ──
    print("── 状态流转: 成功任务 ──")

    # PENDING: 用一个不存在的 task_id 模拟
    fake_result = AsyncResult("non-existent-id", app=app)
    print_result_info(fake_result, "PENDING (未知 task_id)")
    print()

    # SUCCESS: 正常完成的任务
    r1 = await asyncio.to_thread(compute.delay, 10, 20)
    val1 = await asyncio.to_thread(r1.get, timeout=30)  # 先等待任务完成
    print_result_info(r1, "SUCCESS (任务完成)")
    print(f"  get():       {val1}")
    print()

    # ── 状态流转: FAILURE ──
    print("── 状态流转: 失败任务 ──")
    r2 = await asyncio.to_thread(fail_task.delay)
    await asyncio.to_thread(r2.get, timeout=30, propagate=False)  # 等待任务完成，不抛异常
    print_result_info(r2, "FAILURE (任务异常)")
    print(f"  traceback:   {r2.traceback[:80] if r2.traceback else None}...")
    print()

    # ── .get() 参数 ──
    print("── .get() 参数 ──")
    r3 = await asyncio.to_thread(compute.delay, 5, 5)

    # timeout: 最多等待 N 秒
    val = await asyncio.to_thread(r3.get, timeout=30)
    print(f"  ✅ get(timeout=30): {val}")

    # propagate=False: 失败时不抛异常，返回异常对象
    r4 = await asyncio.to_thread(fail_task.delay)
    err = await asyncio.to_thread(r4.get, timeout=30, propagate=False)
    print(f"  ✅ get(propagate=False): {err!r}")
    print(f"     类型: {type(err).__name__}")
    print()

    # ── .forget() 清理结果 ──
    print("── .forget() 清理结果 ──")
    r5 = await asyncio.to_thread(compute.delay, 1, 1)
    task_id = r5.id
    await asyncio.to_thread(r5.get, timeout=30)  # 等待任务完成
    print(f"  清理前 state: {r5.state}")
    r5.forget()
    # forget 后重新查询
    r5_again = AsyncResult(task_id, app=app)
    print(f"  清理后 state: {r5_again.state}")
    print(f"  💡 forget() 从 backend 删除结果，状态回到 PENDING\n")

    # ── 状态一览 ──
    print("── Celery 任务状态一览 ──")
    states: list[tuple[str, str]] = [
        ("PENDING", "任务未知或尚未被 worker 接收"),
        ("RECEIVED", "任务已被 worker 接收 (需要 task_track_started)"),
        ("STARTED", "任务开始执行 (需要 task_track_started=True)"),
        ("SUCCESS", "任务成功完成"),
        ("FAILURE", "任务抛出未捕获异常"),
        ("RETRY", "任务正在重试"),
        ("REVOKED", "任务被撤销"),
    ]
    for state, desc in states:
        print(f"  {state:.<15} {desc}")
    print()

    print("💡 PENDING 不代表任务不存在，也可能是 task_id 错误或结果已过期")
    print("💡 生产中建议设置 result_expires 避免 backend 无限膨胀")


if __name__ == "__main__":
    asyncio.run(main())
