"""
目标: 演示取消任务时如何正确执行资源清理
关键 API: asyncio.CancelledError, task.cancel
Python 版本: 3.11+
运行命令: uv run python examples/04_cancellation/01_cancel_cleanup.py  (从 asyncio教程/ 目录)
预期现象: worker 运行 3 秒后被取消，执行清理逻辑，然后确认取消成功
生产提醒: 处理 CancelledError 后必须重新 raise，否则会破坏取消语义
"""

import asyncio


async def long_running_worker() -> None:
    try:
        while True:
            print("worker is running...")
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        print("worker got cancellation, cleaning up...")
        await asyncio.sleep(0.2)
        print("cleanup finished")
        raise


async def main() -> None:
    task = asyncio.create_task(long_running_worker(), name="long_running_worker")
    await asyncio.sleep(3)

    print("request cancel")
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        print("task cancelled successfully")


if __name__ == "__main__":
    asyncio.run(main())
