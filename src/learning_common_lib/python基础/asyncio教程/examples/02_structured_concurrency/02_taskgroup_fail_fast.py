"""
目标: 演示 TaskGroup 的失败联动取消 —— 一个任务失败时，兄弟任务自动取消，异常包装为 ExceptionGroup
关键 API: asyncio.TaskGroup, except*, asyncio.CancelledError
Python 版本: 3.11+
运行命令: uv run python examples/02_structured_concurrency/02_taskgroup_fail_fast.py  (从 asyncio教程/ 目录)
预期现象: task-B 在 0.5s 后抛出 RuntimeError，task-A 和 task-C 被自动取消，最终捕获 ExceptionGroup
生产提醒: TaskGroup 的失败联动取消是它比 gather() 更适合生产代码的核心原因
"""

import asyncio

cancelled_tasks: list[str] = []


async def task_a() -> str:
    """耗时 2s，正常完成 —— 但会被 task-B 的失败取消。"""
    print("[task-A] 启动，预计 2s 完成")
    try:
        await asyncio.sleep(2.0)
        print("[task-A] 完成")
        return "A-done"
    except asyncio.CancelledError:
        print("[task-A] 被取消!")
        cancelled_tasks.append("task-A")
        raise


async def task_b() -> str:
    """耗时 0.5s 后抛出 RuntimeError，触发 fail-fast。"""
    print("[task-B] 启动，将在 0.5s 后失败")
    await asyncio.sleep(0.5)
    print("[task-B] 抛出 RuntimeError!")
    raise RuntimeError("task-B 模拟故障")


async def task_c() -> str:
    """耗时 1.5s，正常完成 —— 但会被 task-B 的失败取消。"""
    print("[task-C] 启动，预计 1.5s 完成")
    try:
        await asyncio.sleep(1.5)
        print("[task-C] 完成")
        return "C-done"
    except asyncio.CancelledError:
        print("[task-C] 被取消!")
        cancelled_tasks.append("task-C")
        raise


async def main() -> None:
    print("=== TaskGroup fail-fast 演示 ===\n")

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(task_a(), name="task-A")
            tg.create_task(task_b(), name="task-B")
            tg.create_task(task_c(), name="task-C")
    except* RuntimeError as eg:
        print(f"\n捕获 ExceptionGroup，包含 {len(eg.exceptions)} 个异常:")
        for exc in eg.exceptions:
            print(f"  - {type(exc).__name__}: {exc}")

    print(f"\n被取消的任务: {cancelled_tasks}")
    print("结论: task-B 失败后，task-A 和 task-C 被自动取消 —— 这就是 fail-fast。")


if __name__ == "__main__":
    asyncio.run(main())
