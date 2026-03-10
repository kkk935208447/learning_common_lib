"""
目标: 演示 worker pool + 有界队列的背压模式 —— 生产者在队列满时自动阻塞
关键 API: asyncio.Queue, asyncio.TaskGroup, Queue.put, Queue.get
Python 版本: 3.11+
运行命令: uv run python examples/05_backpressure/03_worker_pool.py  (从 asyncio教程/ 目录)
预期现象: 生产者在队列满时阻塞等待，3 个 worker 稳定消费，20 个任务全部完成
生产提醒: worker pool + 有界队列是生产环境最常用的背压模式，比 Semaphore + gather 更可控
"""

import asyncio


async def producer(queue: asyncio.Queue[int | None], total_items: int, num_workers: int) -> None:
    """生产者：向队列放入 total_items 个任务，队列满时自动阻塞。"""
    for i in range(1, total_items + 1):
        print(f"[producer] 放入 item-{i} (队列大小: {queue.qsize()}/{queue.maxsize})", end="")
        await queue.put(i)
        print(" -> 成功")

    # 发送哨兵值通知每个 worker 停止
    for _ in range(num_workers):
        await queue.put(None)
    print("[producer] 所有任务已发送，哨兵值已放入")


async def worker(worker_id: int, queue: asyncio.Queue[int | None], processing_delay: float) -> int:
    """Worker：从队列取任务并处理，遇到 None 哨兵值时退出。"""
    processed: int = 0
    while True:
        item: int | None = await queue.get()
        if item is None:
            queue.task_done()
            print(f"[worker-{worker_id}] 收到哨兵值，退出 (共处理 {processed} 个)")
            return processed

        print(f"[worker-{worker_id}] 处理 item-{item} ...")
        await asyncio.sleep(processing_delay)
        queue.task_done()
        processed += 1
        print(f"[worker-{worker_id}] item-{item} 完成")


async def main() -> None:
    print("=== Worker Pool 背压演示 ===")
    print("队列容量: 5 | Worker 数: 3 | 总任务: 20 | 处理耗时: 0.3s/个\n")

    queue: asyncio.Queue[int | None] = asyncio.Queue(maxsize=5)
    num_workers: int = 3
    total_items: int = 20
    processing_delay: float = 0.3

    async with asyncio.TaskGroup() as tg:
        # 启动 workers
        worker_tasks: list[asyncio.Task[int]] = [
            tg.create_task(worker(i, queue, processing_delay), name=f"worker-{i}")
            for i in range(1, num_workers + 1)
        ]
        # 启动 producer
        tg.create_task(producer(queue, total_items, num_workers), name="producer")

    # 统计结果
    total_processed: int = sum(t.result() for t in worker_tasks)
    print(f"\n所有 worker 共处理: {total_processed} 个任务")
    print("结论: 有界队列让生产者在队列满时自动阻塞，实现天然的背压控制。")


if __name__ == "__main__":
    asyncio.run(main())
