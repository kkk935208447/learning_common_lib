"""
目标: 对比顺序执行与 gather 并发执行的耗时差异
关键 API: asyncio.gather, asyncio.sleep
Python 版本: 3.11+
运行命令: uv run python examples/01_basics/02_sequential_vs_gather.py  (从 asyncio教程/ 目录)
预期现象: 顺序执行约 4.5 秒，并发执行约 2 秒
生产提醒: gather 适合"全部完成再继续"的场景，部分失败需配合 return_exceptions
"""

import asyncio
import time


async def worker(name: str, delay: float) -> str:
    print(f"[{name}] start")
    await asyncio.sleep(delay)
    print(f"[{name}] end")
    return f"{name} done"


async def run_sequential() -> None:
    print("\n=== sequential ===")
    started = time.perf_counter()

    results = []
    results.append(await worker("A", 2))
    results.append(await worker("B", 1))
    results.append(await worker("C", 1.5))

    elapsed = time.perf_counter() - started
    print("sequential results:", results)
    print(f"sequential elapsed={elapsed:.2f}s")


async def run_concurrent() -> None:
    print("\n=== concurrent gather ===")
    started = time.perf_counter()

    results = await asyncio.gather(
        worker("A", 2),
        worker("B", 1),
        worker("C", 1.5),
    )

    elapsed = time.perf_counter() - started
    print("concurrent results:", results)
    print(f"concurrent elapsed={elapsed:.2f}s")


async def main() -> None:
    await run_sequential()
    await run_concurrent()


if __name__ == "__main__":
    asyncio.run(main())
