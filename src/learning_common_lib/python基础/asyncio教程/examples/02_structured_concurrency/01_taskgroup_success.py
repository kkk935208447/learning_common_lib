"""
目标: 演示 TaskGroup 的基本用法——多任务并发执行与结果收集
关键 API: asyncio.TaskGroup
Python 版本: 3.11+
运行命令: uv run python examples/02_structured_concurrency/01_taskgroup_success.py  (从 asyncio教程/ 目录)
预期现象: 3 个任务并发执行，全部成功，打印结果列表
生产提醒: TaskGroup 是 Python 3.11+ 推荐的并发管理方式，替代裸 gather
"""

import asyncio


async def worker(name: str, delay: float) -> str:
    print(f"{name} started")
    await asyncio.sleep(delay)
    print(f"{name} finished")
    return f"{name} ok"


async def main() -> None:
    tasks: list[asyncio.Task[str]] = []

    async with asyncio.TaskGroup() as tg:
        tasks.append(tg.create_task(worker("task-A", 1.0)))
        tasks.append(tg.create_task(worker("task-B", 2.0)))
        tasks.append(tg.create_task(worker("task-C", 1.5)))

    results = [task.result() for task in tasks]
    print("results:", results)


if __name__ == "__main__":
    asyncio.run(main())
