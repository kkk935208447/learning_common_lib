"""
目标: 用 async task 演示 AsyncResult 的状态与结果可用性 (AsyncResult with async tasks)
关键概念:
  - worker 侧任务已经切到 `custom aio pool + async def task`
  - AsyncResult 仍然是客户端接口，查询结果时通常需要线程包装
  - PENDING / SUCCESS / FAILURE / forget 后回到 PENDING 的语义不变
关键 API: AsyncResult, .get(), .state, .ready(), .successful(), .failed(), .forget()
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/05_result_backend
运行方式:
  Worker:
    CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool' \
    celery -A examples.05_result_backend.01_async_result worker -l info -P custom -Q aio_results -c 20
  Client:
    python examples/05_result_backend/01_async_result.py
预期现象:
  - worker 执行的是 async def task
  - 状态机语义与同步任务时代一致
  - forget() 删除结果后，重新查询会回到 PENDING
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery
from celery.result import AsyncResult

MODULE = "examples.05_result_backend.01_async_result"

app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.update(
    task_default_queue="aio_results",
    task_track_started=True,
)


def print_section(title: str) -> None:
    print(f"── {title} ──")


@app.task(bind=True, name=f"{MODULE}.compute")
async def compute(self: Any, x: int, y: int) -> int:
    await asyncio.sleep(0.2)
    return x + y


@app.task(bind=True, name=f"{MODULE}.fail_task")
async def fail_task(self: Any) -> None:
    await asyncio.sleep(0.1)
    raise ValueError("故意抛出的错误")


def snapshot(result: AsyncResult) -> dict[str, Any]:
    return {
        "task_id": result.id,
        "state": result.state,
        "ready": result.ready(),
        "successful": result.successful(),
        "failed": result.failed(),
        "info": repr(result.info),
    }


async def print_snapshot(label: str, result: AsyncResult) -> None:
    data = await asyncio.to_thread(snapshot, result)
    print(f"  📋 {label}: {data}")


async def main() -> None:
    print("🚀 AsyncResult 状态与结果可用性对比（async task）\n")

    print_section("场景 A: PENDING 不一定代表“任务在排队”")
    fake_result = AsyncResult("non-existent-id", app=app)
    await print_snapshot("未知 task_id", fake_result)
    print("  结论: PENDING 既可能是任务还没跑，也可能是 task_id 错了，或结果已经被删掉。\n")

    print_section("场景 B: SUCCESS 与 FAILURE 都是 ready=True")
    success_result = await asyncio.to_thread(compute.delay, 10, 20)
    failure_result = await asyncio.to_thread(fail_task.delay)

    success_value = await asyncio.to_thread(success_result.get, timeout=30)
    failure_value = await asyncio.to_thread(failure_result.get, timeout=30, propagate=False)

    await print_snapshot("SUCCESS", success_result)
    print(f"  get(): {success_value}")
    print()
    await print_snapshot("FAILURE", failure_result)
    print(f"  get(propagate=False): {failure_value!r}")
    print("  结论: ready=True 只表示“任务结束了”，不表示它成功了。\n")

    print_section("场景 C: 同一个 .get()，成功和失败语义不同")
    retry_success = await asyncio.to_thread(compute.delay, 5, 5)
    print(f"  ✅ 成功任务 get(timeout=30): {await asyncio.to_thread(retry_success.get, timeout=30)}")

    retry_failure = await asyncio.to_thread(fail_task.delay)
    err = await asyncio.to_thread(retry_failure.get, timeout=30, propagate=False)
    print(f"  ✅ 失败任务 get(propagate=False): {err!r}")
    print(f"     类型: {type(err).__name__}")
    print("  结论: 即使 worker 已 async-first，结果查询客户端接口仍然主要是同步风格。\n")

    print_section("场景 D: forget() 删除结果后，状态会回到 PENDING")
    forget_result = await asyncio.to_thread(compute.delay, 1, 1)
    task_id = forget_result.id
    await asyncio.to_thread(forget_result.get, timeout=30)
    await print_snapshot("forget 前", forget_result)
    await asyncio.to_thread(forget_result.forget)
    await print_snapshot("forget 后重新查询", AsyncResult(task_id, app=app))
    print("  结论: PENDING 还可能表示结果被 backend 清掉了。\n")

    print_section("状态 vs 结果可用性总结")
    rows = [
        ("PENDING", "通常拿不到结果", "任务未完成 / task_id 错误 / 结果过期"),
        ("SUCCESS", "能拿到返回值", "result 就是任务返回值"),
        ("FAILURE", "能拿到异常信息", "result/info/traceback 指向错误"),
        ("forget 后查询", "回到 PENDING", "backend 结果已被删除"),
    ]
    for state, availability, meaning in rows:
        print(f"  {state:<14} {availability:<18} {meaning}")


if __name__ == "__main__":
    asyncio.run(main())
