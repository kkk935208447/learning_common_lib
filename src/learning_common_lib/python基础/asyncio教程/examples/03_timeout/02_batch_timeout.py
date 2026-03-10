"""
目标: 演示对一批并发任务施加统一超时 —— asyncio.timeout() 包裹 TaskGroup
关键 API: asyncio.timeout, asyncio.TaskGroup, asyncio.TimeoutError
Python 版本: 3.11+
运行命令: uv run python examples/03_timeout/02_batch_timeout.py  (从 asyncio教程/ 目录)
预期现象: 4 个任务中前三个在 2s 内完成，第四个(3s)因批量超时被取消
生产提醒: 批量超时要和单任务超时配合使用，避免慢任务拖垮整批
"""

import asyncio


async def worker(name: str, delay: float) -> str:
    """模拟一个耗时任务。"""
    print(f"[{name}] 启动，预计 {delay}s 完成")
    try:
        await asyncio.sleep(delay)
        print(f"[{name}] 完成 ✓")
        return f"{name}-done"
    except asyncio.CancelledError:
        print(f"[{name}] 被超时取消!")
        raise


async def main() -> None:
    print("=== 批量超时演示 ===")
    print("批量超时: 2.0s | 任务耗时: 0.5s, 1.0s, 1.5s, 3.0s\n")

    tasks_config: list[tuple[str, float]] = [
        ("fast-1", 0.5),
        ("fast-2", 1.0),
        ("medium", 1.5),
        ("slow", 3.0),
    ]

    try:
        async with asyncio.timeout(2.0):
            async with asyncio.TaskGroup() as tg:
                for name, delay in tasks_config:
                    tg.create_task(worker(name, delay), name=name)
    except TimeoutError:
        print("\n批量超时触发! 所有未完成的任务已被取消。")

    print("\n结论: asyncio.timeout() 包裹 TaskGroup 可以对整批任务施加统一的时间上限。")


if __name__ == "__main__":
    asyncio.run(main())
