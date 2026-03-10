"""
目标: 演示用进程池执行 CPU 密集任务
关键 API: asyncio.get_running_loop, ProcessPoolExecutor
Python 版本: 3.11+
运行命令: uv run python examples/07_blocking_bridge/02_process_pool.py  (从 asyncio教程/ 目录)
预期现象: CPU 密集计算在进程池中并行执行，不阻塞事件循环
生产提醒: 进程池有启动开销，适合重计算任务，轻量任务用 to_thread 即可
"""

import asyncio
from concurrent.futures import ProcessPoolExecutor


def cpu_heavy(task_id: int) -> int:
    total = 0
    for i in range(3_000_000):
        total += i * task_id
    return total


async def main() -> None:
    loop = asyncio.get_running_loop()

    with ProcessPoolExecutor() as pool:
        futures = [
            loop.run_in_executor(pool, cpu_heavy, i)
            for i in range(1, 5)
        ]
        results = await asyncio.gather(*futures)

    print("results:", results)


if __name__ == "__main__":
    asyncio.run(main())
