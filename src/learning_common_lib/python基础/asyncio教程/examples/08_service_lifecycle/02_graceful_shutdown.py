"""
目标: 演示服务程序的优雅关闭流程
关键 API: signal, asyncio.Event, task.cancel
Python 版本: 3.11+
运行命令: uv run python examples/08_service_lifecycle/02_graceful_shutdown.py  (从 asyncio教程/ 目录)
预期现象: 服务启动后按 Ctrl+C，worker 收到取消信号并执行清理
生产提醒: Windows 环境下 add_signal_handler 可能不可用，需要 fallback 方案
"""

import asyncio
import logging
import signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger(__name__)

shutdown_event = asyncio.Event()


async def worker(name: str) -> None:
    try:
        while not shutdown_event.is_set():
            logger.info("%s running", name)
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("%s cleaning up", name)
        raise


async def main() -> None:
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            # Windows fallback: use signal.signal in main thread
            signal.signal(sig, lambda s, f: shutdown_event.set())

    tasks = [
        asyncio.create_task(worker("worker-1"), name="worker-1"),
        asyncio.create_task(worker("worker-2"), name="worker-2"),
    ]

    logger.info("service started, press Ctrl+C to stop")
    await shutdown_event.wait()
    logger.info("shutdown signal received")

    for task in tasks:
        task.cancel()

    results = await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("workers stopped: %s", results)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("keyboard interrupt")
