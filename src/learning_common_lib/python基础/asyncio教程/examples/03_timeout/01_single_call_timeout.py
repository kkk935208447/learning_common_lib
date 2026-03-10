"""
目标: 演示为单个异步调用设置超时
关键 API: asyncio.timeout
Python 版本: 3.11+
运行命令: uv run python examples/03_timeout/01_single_call_timeout.py  (从 asyncio教程/ 目录)
预期现象: 快速调用(1s)成功返回，慢速调用(3s)触发 TimeoutError 被捕获
生产提醒: 所有外部调用都应设置超时，防止任务无限等待导致资源堆积
"""

import asyncio


async def remote_call(delay: float) -> str:
    await asyncio.sleep(delay)
    return f"response after {delay}s"


async def main() -> None:
    # 场景 1: 快速调用，在超时内完成
    print("场景 1: 快速调用 (1s)，超时 2s")
    try:
        async with asyncio.timeout(2):
            result = await remote_call(1)
            print(f"  成功: {result}")
    except TimeoutError:
        print("  超时!")

    # 场景 2: 慢速调用，超时触发
    print("\n场景 2: 慢速调用 (3s)，超时 2s")
    try:
        async with asyncio.timeout(2):
            result = await remote_call(3)
            print(f"  成功: {result}")
    except TimeoutError:
        print("  超时! 调用已安全取消")


if __name__ == "__main__":
    asyncio.run(main())
