"""
目标: 演示后台任务的生命周期管理 —— 注册、异常回收、优雅关闭
关键 API: asyncio.create_task, Task.add_done_callback, Task.cancel
Python 版本: 3.11+
运行命令: uv run python examples/08_service_lifecycle/01_background_tasks.py  (从 asyncio教程/ 目录)
预期现象: 3 个后台任务启动，1 个正常完成，1 个异常被回调捕获，1 个在 shutdown 时被取消
生产提醒: 后台任务必须有异常回收和 shutdown 入口，否则异常会静默丢失
"""

import asyncio


# ── 任务注册表 ────────────────────────────────────────────

task_registry: set[asyncio.Task[None]] = set()


def register_task(task: asyncio.Task[None]) -> None:
    """注册任务并添加 done_callback。"""
    task_registry.add(task)
    task.add_done_callback(_task_done_callback)
    print(f"[registry] 注册任务: {task.get_name()}")


def _task_done_callback(task: asyncio.Task[None]) -> None:
    """任务完成时的回调 —— 捕获异常，防止静默丢失。"""
    task_registry.discard(task)
    if task.cancelled():
        print(f"[callback] {task.get_name()} 被取消")
        return
    exc = task.exception()
    if exc is not None:
        print(f"[callback] {task.get_name()} 异常被捕获: {type(exc).__name__}: {exc}")
    else:
        print(f"[callback] {task.get_name()} 正常完成")


# ── 后台任务 ──────────────────────────────────────────────

async def normal_task() -> None:
    """正常完成的任务。"""
    print("[normal] 启动，将在 0.5s 后完成")
    await asyncio.sleep(0.5)
    print("[normal] 工作完成")


async def failing_task() -> None:
    """1s 后抛出异常的任务。"""
    print("[failing] 启动，将在 1.0s 后抛出异常")
    await asyncio.sleep(1.0)
    raise RuntimeError("模拟数据库连接断开")


async def long_running_task() -> None:
    """持续运行的任务，需要在 shutdown 时被取消。"""
    print("[long-running] 启动，将持续运行直到被取消")
    try:
        while True:
            await asyncio.sleep(0.5)
            print("[long-running] 心跳 ...")
    except asyncio.CancelledError:
        print("[long-running] 收到取消信号，执行清理")
        await asyncio.sleep(0.1)  # 模拟清理工作
        print("[long-running] 清理完成")
        raise


# ── 优雅关闭 ──────────────────────────────────────────────

async def shutdown() -> None:
    """取消所有注册的后台任务并等待它们完成清理。"""
    print(f"\n[shutdown] 开始关闭，剩余任务: {len(task_registry)} 个")
    tasks_to_cancel = list(task_registry)
    for task in tasks_to_cancel:
        print(f"[shutdown] 取消 {task.get_name()}")
        task.cancel()

    if tasks_to_cancel:
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
    print("[shutdown] 所有任务已关闭")


# ── 主流程 ────────────────────────────────────────────────

async def main() -> None:
    print("=== 后台任务生命周期管理演示 ===\n")

    # 注册 3 个后台任务
    t1 = asyncio.create_task(normal_task(), name="normal")
    t2 = asyncio.create_task(failing_task(), name="failing")
    t3 = asyncio.create_task(long_running_task(), name="long-running")

    register_task(t1)
    register_task(t2)
    register_task(t3)

    print()

    # 等待 3s，让 normal 完成、failing 抛异常、long-running 持续运行
    await asyncio.sleep(3.0)

    # 触发优雅关闭
    await shutdown()

    print("\n结论: done_callback 防止异常静默丢失，shutdown 确保所有任务被清理。")


if __name__ == "__main__":
    asyncio.run(main())
