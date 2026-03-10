"""
目标: 演示使用 Semaphore 限制最大并发数
关键 API: asyncio.Semaphore, asyncio.gather
Python 版本: 3.11+
运行命令: uv run python examples/05_backpressure/01_semaphore_limit.py  (从 asyncio教程/ 目录)
预期现象: 虽然有多个任务，但同时运行的不超过设定的并发上限
生产提醒: Semaphore 控制并发数但不控制队列深度，大批量场景建议配合有界队列
"""

import asyncio
import random


async def call_api(item_id: int, sem: asyncio.Semaphore) -> dict:
    async with sem:
        delay = random.uniform(0.5, 1.5)
        print(f"start item={item_id}, delay={delay:.2f}s")
        await asyncio.sleep(delay)
        print(f"end item={item_id}")
        return {"item_id": item_id, "delay": round(delay, 2)}


async def main() -> None:
    sem = asyncio.Semaphore(3)
    tasks = [call_api(i, sem) for i in range(10)]
    results = await asyncio.gather(*tasks)
    print("results:", results)


if __name__ == "__main__":
    asyncio.run(main())
