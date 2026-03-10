"""
目标: 演示取消如何在嵌套 TaskGroup 中逐层传播 —— 外层取消会递归取消所有内层任务
关键 API: asyncio.TaskGroup, asyncio.CancelledError, task.cancel()
Python 版本: 3.11+
运行命令: uv run python examples/04_cancellation/02_cancel_propagation.py  (从 asyncio教程/ 目录)
预期现象: 外层任务在 1s 后被取消，所有内层任务依次收到 CancelledError
生产提醒: 取消传播是结构化并发的核心保证，不要用 shield() 破坏它，除非你明确知道为什么
"""

import asyncio


async def inner_task(group_name: str, task_name: str, delay: float) -> None:
    """内层任务：打印启动和取消信息。"""
    print(f"  [{group_name}/{task_name}] 启动，预计 {delay}s 完成")
    try:
        await asyncio.sleep(delay)
        print(f"  [{group_name}/{task_name}] 完成")
    except asyncio.CancelledError:
        print(f"  [{group_name}/{task_name}] 收到 CancelledError!")
        raise


async def inner_group_a() -> None:
    """内层 TaskGroup A，包含 2 个任务。"""
    print("[Group-A] 启动")
    async with asyncio.TaskGroup() as tg:
        tg.create_task(inner_task("A", "a1", 3.0))
        tg.create_task(inner_task("A", "a2", 4.0))
    print("[Group-A] 完成")


async def inner_group_b() -> None:
    """内层 TaskGroup B，包含 2 个任务。"""
    print("[Group-B] 启动")
    async with asyncio.TaskGroup() as tg:
        tg.create_task(inner_task("B", "b1", 5.0))
        tg.create_task(inner_task("B", "b2", 6.0))
    print("[Group-B] 完成")


async def outer_work() -> None:
    """外层任务：创建两个内层 TaskGroup。"""
    print("[Outer] 启动外层 TaskGroup")
    async with asyncio.TaskGroup() as tg:
        tg.create_task(inner_group_a())
        tg.create_task(inner_group_b())
    print("[Outer] 完成")


async def main() -> None:
    print("=== 取消传播演示 ===")
    print("计划: 1s 后从外部取消，观察取消如何传播到所有内层任务\n")

    outer_task: asyncio.Task[None] = asyncio.create_task(outer_work(), name="outer")

    # 等待 1s 后从外部取消
    await asyncio.sleep(1.0)
    print("\n--- 1s 到，从外部取消 outer_task ---\n")
    outer_task.cancel()

    try:
        await outer_task
    except asyncio.CancelledError:
        print("\n[main] outer_task 已被取消")

    print("\n结论: 取消从外层 TaskGroup 传播到所有内层 TaskGroup 的每个任务。")


if __name__ == "__main__":
    asyncio.run(main())
