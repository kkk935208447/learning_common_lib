"""
目标: 演示生产者-消费者模型与有界队列的背压效果
关键 API: asyncio.Queue
Python 版本: 3.11+
运行命令: uv run python examples/05_backpressure/02_bounded_queue.py  (从 asyncio教程/ 目录)
预期现象: 生产者在队列满时阻塞等待，消费者持续处理，形成自然背压
生产提醒: 有界队列是最简单的背压机制，maxsize 要根据内存和下游承受能力设置
"""

import asyncio

SENTINEL = object()


async def producer(queue: asyncio.Queue, n_consumers: int) -> None:
    for i in range(20):
        await queue.put(i)
        print(f"produced: {i}")

    for _ in range(n_consumers):
        await queue.put(SENTINEL)


async def consumer(name: str, queue: asyncio.Queue) -> None:
    while True:
        item = await queue.get()
        try:
            if item is SENTINEL:
                print(f"{name} exiting")
                return
            print(f"{name} processing {item}")
            await asyncio.sleep(0.5)
        finally:
            queue.task_done()


async def main() -> None:
    queue = asyncio.Queue(maxsize=10)
    n_consumers = 3

    async with asyncio.TaskGroup() as tg:
        tg.create_task(producer(queue, n_consumers))
        for i in range(n_consumers):
            tg.create_task(consumer(f"consumer-{i}", queue))

    await queue.join()
    print("all items processed")


if __name__ == "__main__":
    asyncio.run(main())
