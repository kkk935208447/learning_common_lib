"""
目标: 演示用 asyncio.to_thread 桥接同步阻塞函数
关键 API: asyncio.to_thread
Python 版本: 3.11+
运行命令: uv run python examples/07_blocking_bridge/01_to_thread.py  (从 asyncio教程/ 目录)
预期现象: 阻塞函数在线程中执行，不阻塞事件循环，异步任务正常并发
生产提醒: to_thread 只是桥接方案，高频调用仍应寻找原生异步实现
"""

import asyncio
import time


def blocking_io(task_id: int) -> str:
    time.sleep(2)
    return f"blocking result from task {task_id}"


async def worker(task_id: int) -> str:
    return await asyncio.to_thread(blocking_io, task_id)


async def main() -> None:
    started = time.perf_counter()
    results = await asyncio.gather(*(worker(i) for i in range(5)))
    elapsed = time.perf_counter() - started

    print("results:", results)
    print(f"elapsed={elapsed:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
