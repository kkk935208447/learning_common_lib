# worker.py
import asyncio
from .taskiq_app import broker


async def main():
    """
    启动 TaskIQ Worker
    """
    print("=" * 60)
    print("🚀 TaskIQ Worker 启动中...")
    print("📡 监听 Redis 队列: redis://localhost:6379/0")
    print("=" * 60)
    
    # 启动 broker（开始监听任务）
    await broker.startup()
    
    # 保持运行
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\n🛑 Worker 正在关闭...")
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())