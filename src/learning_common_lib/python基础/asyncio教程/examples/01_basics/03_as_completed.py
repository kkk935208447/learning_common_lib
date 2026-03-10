"""
目标: 演示按完成顺序处理并发任务结果
关键 API: asyncio.as_completed, asyncio.create_task
Python 版本: 3.11+
运行命令: uv run python examples/01_basics/03_as_completed.py  (从 asyncio教程/ 目录)
预期现象: 4 个任务按完成先后顺序输出结果，而非提交顺序
生产提醒: as_completed 适合"先到先处理"场景，如多源查询取最快结果
"""

import asyncio
import random

random.seed(42)  # 固定种子，确保输出可复现


async def query_source(name: str) -> str:
    delay = random.uniform(0.5, 2.5)
    await asyncio.sleep(delay)
    return f"{name} finished in {delay:.2f}s"


async def main() -> None:
    tasks = [
        asyncio.create_task(query_source("source-A"), name="source-A"),
        asyncio.create_task(query_source("source-B"), name="source-B"),
        asyncio.create_task(query_source("source-C"), name="source-C"),
        asyncio.create_task(query_source("source-D"), name="source-D"),
    ]

    print("按完成顺序处理结果：")
    for future in asyncio.as_completed(tasks):
        result = await future
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
