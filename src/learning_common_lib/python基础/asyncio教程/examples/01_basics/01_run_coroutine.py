"""
目标: 演示最简单的协程定义与运行
关键 API: asyncio.run, asyncio.sleep
Python 版本: 3.11+
运行命令: uv run python examples/01_basics/01_run_coroutine.py  (从 asyncio教程/ 目录)
预期现象: 打印 hello，等待 1 秒，打印 world，显示耗时约 1 秒
生产提醒: asyncio.run() 是程序唯一入口，不要在已有事件循环中调用
"""

import asyncio
import time


async def say_hello() -> str:
    print("hello")
    await asyncio.sleep(1)
    print("world")
    return "done"


async def main() -> None:
    started = time.perf_counter()
    result = await say_hello()
    elapsed = time.perf_counter() - started

    print(f"result={result}")
    print(f"elapsed={elapsed:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
