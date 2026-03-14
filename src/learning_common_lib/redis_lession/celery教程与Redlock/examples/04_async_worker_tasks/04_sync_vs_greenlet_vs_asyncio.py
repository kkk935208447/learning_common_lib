"""
目标: 汇总比较 prefork、官方 greenlet pool、custom aio pool (Decision Table)
关键概念:
  - 第 01 节是 prefork 基线
  - 第 02 节是官方 gevent 中间态
  - 第 03 节是 custom aio pool 的 async def task
  - 本文件不再跑任务，而是把三条路线的差异一次收束清楚
关键 API: 无；本文件是对比总结脚本
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/04_async_worker_tasks
运行方式:
  Client: python examples/04_async_worker_tasks/04_sync_vs_greenlet_vs_asyncio.py
预期现象:
  - 读者能在一个表里看懂三条路线的 task 形态、并发模型、适用场景和限制
"""

from __future__ import annotations


def print_section(title: str) -> None:
    print(f"── {title} ──")


def print_table(rows: list[dict[str, str]]) -> None:
    headers = ("路线", "task 写法", "worker pool", "并发模型", "最适合")
    widths = (18, 14, 20, 14, 28)
    print(
        f"  {headers[0]:<{widths[0]}} {headers[1]:<{widths[1]}} "
        f"{headers[2]:<{widths[2]}} {headers[3]:<{widths[3]}} {headers[4]:<{widths[4]}}"
    )
    print(f"  {'-' * (sum(widths) + 4)}")
    for row in rows:
        print(
            f"  {row['route']:<{widths[0]}} {row['task_shape']:<{widths[1]}} "
            f"{row['worker_pool']:<{widths[2]}} {row['concurrency']:<{widths[3]}} "
            f"{row['best_for']:<{widths[4]}}"
        )


def main() -> None:
    print("🚀 prefork → gevent → custom aio pool 总对比\n")

    print_section("前 3 个示例各自解决什么问题")
    intros = [
        ("01_sync_worker_baseline.py", "建立 prefork 基线，说明 producer async 不等于 worker async。"),
        ("02_official_greenlet_pools.py", "证明 gevent 是官方中间态，但 task 仍是 sync def。"),
        ("03_custom_aio_pool_async_task.py", "跑通真正的 async def task 和 asyncio worker。"),
    ]
    for filename, note in intros:
        print(f"  {filename:<36} {note}")
    print()

    print_section("三条路线并排总表")
    rows = [
        {
            "route": "prefork",
            "task_shape": "sync def",
            "worker_pool": "prefork",
            "concurrency": "多进程",
            "best_for": "CPU / 阻塞式 SDK / 默认基线",
        },
        {
            "route": "gevent",
            "task_shape": "sync def",
            "worker_pool": "官方 greenlet",
            "concurrency": "greenlet",
            "best_for": "cooperative IO 的中间态",
        },
        {
            "route": "custom aio pool",
            "task_shape": "async def",
            "worker_pool": "AsyncIOPool",
            "concurrency": "asyncio",
            "best_for": "原生 asyncio IO",
        },
    ]
    print_table(rows)
    print()

    print_section("最容易误解的 3 件事")
    misunderstandings = [
        "`asyncio.to_thread(task.delay, ...)` 只解决 producer 侧不阻塞，不会自动把 worker 变成 async。",
        "`gevent` 是官方并发池，但它不是原生 async def task 方案。",
        "`custom aio pool` 让 worker 能执行 async def task，但 Celery 客户端 API 仍然主要是同步风格。",
    ]
    for line in misunderstandings:
        print(f"  - {line}")
    print()

    print_section("工程决策建议")
    decisions = [
        ("旧项目 / 阻塞式 SDK", "先用 prefork，必要时在 sync task 里 asyncio.run()"),
        ("cooperative IO 已成熟", "可以考虑官方 gevent 中间态"),
        ("明确走 asyncio 生态", "拆独立 aio 队列 + custom aio pool"),
        ("混合工作负载", "分队列、分 worker 组，而不是一个 worker 池硬吃全部"),
    ]
    for scenario, recommendation in decisions:
        print(f"  {scenario:<22} {recommendation}")


if __name__ == "__main__":
    main()
