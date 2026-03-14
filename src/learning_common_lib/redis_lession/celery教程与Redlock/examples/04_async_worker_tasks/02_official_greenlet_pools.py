"""
目标: 用批量并发测试对比 prefork 与 gevent (Prefork vs gevent by Batch Concurrency)
关键概念:
  - prefork: 多进程池，适合 CPU 任务和阻塞式同步代码
  - gevent: 官方 greenlet 池，适合等待型 / cooperative IO 任务
  - 对比重点: 同一类等待型任务，分别投到 prefork 队列和 gevent 队列，观察总耗时差异
关键 API: task_routes, task.delay(), result.get()
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/04_async_worker_tasks
运行方式:
  Worker 1 (prefork):
    celery -A examples.04_async_worker_tasks.02_official_greenlet_pools worker -l info -P prefork -c 2 -Q prefork_jobs
  Worker 2 (gevent):
    celery -A examples.04_async_worker_tasks.02_official_greenlet_pools worker -l info -P gevent -c 20 -Q greenlet_jobs
  Client:
    python examples/04_async_worker_tasks/02_official_greenlet_pools.py
预期现象:
  - 两边执行的都还是 sync def task
  - 在多任务并发等待场景里，gevent 总耗时通常明显短于低并发 prefork
  - 这说明 gevent 是“官方中间态”，但不是原生 async def task
生产提醒:
  - gevent 更适合等待型任务，不适合 CPU 密集型任务
  - gevent 仍然是 sync def task；如果你要真正跑 async def，应使用 custom aio pool
技术要点:
  - 为了放大差异，本示例使用 prefork `-c 2`，gevent `-c 20`
  - 这里比较的是两种 worker pool 的运行效果，不再拿 greenlet API 自己作对比
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from celery import Celery

MODULE = "examples.04_async_worker_tasks.02_official_greenlet_pools"
PREFORK_QUEUE = "prefork_jobs"
GEVENT_QUEUE = "greenlet_jobs"
BATCH_SIZE = 6
TASK_SECONDS = 1.0

app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.update(
    task_default_queue=PREFORK_QUEUE,
    task_routes={
        f"{MODULE}.prefork_wait_task": {"queue": PREFORK_QUEUE},
        f"{MODULE}.gevent_wait_task": {"queue": GEVENT_QUEUE},
    },
)


def print_section(title: str) -> None:
    print(f"── {title} ──")


@app.task(bind=True, name=f"{MODULE}.prefork_wait_task")
def prefork_wait_task(self: Any, label: str, seconds: float = TASK_SECONDS) -> dict[str, Any]:
    started = time.perf_counter()
    time.sleep(seconds)
    return {
        "task_id": self.request.id,
        "label": label,
        "task_shape": "sync def",
        "worker_pool": "prefork",
        "elapsed_s": round(time.perf_counter() - started, 3),
    }


@app.task(bind=True, name=f"{MODULE}.gevent_wait_task")
def gevent_wait_task(self: Any, label: str, seconds: float = TASK_SECONDS) -> dict[str, Any]:
    started = time.perf_counter()
    time.sleep(seconds)
    return {
        "task_id": self.request.id,
        "label": label,
        "task_shape": "sync def",
        "worker_pool": "gevent",
        "elapsed_s": round(time.perf_counter() - started, 3),
    }


async def main() -> None:
    print("🚀 prefork vs gevent 并发对比示例\n")

    print_section("场景 A: 两边执行的都还是 sync def task")
    prefork_single = await asyncio.to_thread(prefork_wait_task.delay, "prefork-single", 0.2)
    gevent_single = await asyncio.to_thread(gevent_wait_task.delay, "gevent-single", 0.2)
    prefork_single_payload = await asyncio.to_thread(prefork_single.get, timeout=30)
    gevent_single_payload = await asyncio.to_thread(gevent_single.get, timeout=30)
    print(f"  ✅ prefork 单任务: {prefork_single_payload}")
    print(f"  ✅ gevent  单任务: {gevent_single_payload}")
    print("  结论: gevent 不是 async def task；它和 prefork 一样，执行体仍然是 sync def。\n")

    print_section("场景 B: 批量并发测试 prefork")
    prefork_started = time.perf_counter()
    prefork_results = await asyncio.gather(
        *(asyncio.to_thread(prefork_wait_task.delay, f"prefork-{index}", TASK_SECONDS) for index in range(BATCH_SIZE))
    )
    prefork_payloads = await asyncio.gather(
        *(asyncio.to_thread(result.get, timeout=30) for result in prefork_results)
    )
    prefork_total = round(time.perf_counter() - prefork_started, 3)
    print(f"  ✅ prefork 总耗时: {prefork_total}s")
    print(f"  ✅ 返回数量: {len(prefork_payloads)}")
    print("  结论: prefork 并发度受子进程数限制，本例使用 -c 2，所以会分多轮完成。\n")

    print_section("场景 C: 批量并发测试 gevent")
    gevent_started = time.perf_counter()
    gevent_results = await asyncio.gather(
        *(asyncio.to_thread(gevent_wait_task.delay, f"gevent-{index}", TASK_SECONDS) for index in range(BATCH_SIZE))
    )
    gevent_payloads = await asyncio.gather(
        *(asyncio.to_thread(result.get, timeout=30) for result in gevent_results)
    )
    gevent_total = round(time.perf_counter() - gevent_started, 3)
    print(f"  ✅ gevent 总耗时: {gevent_total}s")
    print(f"  ✅ 返回数量: {len(gevent_payloads)}")
    print("  结论: gevent 更适合等待型任务；在高并发 worker 配置下，批量任务会更快完成。\n")

    print_section("最终判断")
    rows = [
        ("prefork", "sync def", "多进程", "CPU / 阻塞式同步代码", prefork_total),
        ("gevent", "sync def", "greenlet", "等待型任务 / cooperative IO", gevent_total),
    ]
    print("  路线       task 写法     并发模型       适合场景                     本次总耗时")
    print("  ---------------------------------------------------------------------------")
    for route, task_shape, pool_model, scenario, total in rows:
        print(f"  {route:<10} {task_shape:<12} {pool_model:<12} {scenario:<26} {total}s")
    print()
    print("  结论 1: gevent 是官方中间态，核心价值是提高等待型任务的吞吐。")
    print("  结论 2: 它仍然不是原生 async def task；如果要真正跑 asyncio，请转到第 03 节。")


if __name__ == "__main__":
    asyncio.run(main())
