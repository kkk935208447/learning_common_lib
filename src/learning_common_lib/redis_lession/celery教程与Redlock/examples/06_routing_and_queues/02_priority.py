"""
目标: 优先级队列配置，演示任务优先级调度概念
关键 API: apply_async(priority=N), broker_transport_options, task_queue_max_priority
Python 版本: 3.11+
运行命令:
  终端 1 (启动 Worker):
    celery -A examples.06_routing_and_queues.02_priority worker -l info -P solo
  终端 2 (运行示例):
    uv run python examples/06_routing_and_queues/02_priority.py
  (从 src/learning_common_lib/redis_lession/celery教程与Redlock 目录)
预期现象: 打印不同优先级任务的调度信息，说明优先级机制
生产提醒: Redis 优先级支持有限(仅模拟)，RabbitMQ 原生支持 0-255 优先级
"""

from __future__ import annotations

import asyncio

from celery import Celery

# ── 1. 创建 Celery 应用并配置优先级 ──
app = Celery(
    "examples.06_routing_and_queues.02_priority",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)

app.conf.update(
    # Redis 优先级配置
    # Redis 通过创建多个 list (queue_name\x06\x16\x06priority) 模拟优先级
    broker_transport_options={
        "priority_steps": list(range(10)),  # 支持 0-9 优先级
        "sep": "\x06\x16\x06",             # 优先级队列分隔符
        "queue_order_strategy": "priority", # 启用优先级策略
    },
    # 队列最大优先级 (RabbitMQ 专用，Redis 忽略此项)
    task_queue_max_priority=9,
    task_default_priority=5,  # 默认优先级
)


# ── 2. 定义不同优先级的任务 ──
@app.task
def critical_alert(message: str) -> dict[str, str]:
    """紧急告警 — 最高优先级"""
    print(f"  🚨 紧急告警: {message}")
    return {"level": "critical", "message": message}


@app.task
def normal_process(data: str) -> dict[str, str]:
    """普通处理 — 中等优先级"""
    print(f"  ⚙️ 普通处理: {data}")
    return {"level": "normal", "data": data}


@app.task
def background_cleanup(target: str) -> dict[str, str]:
    """后台清理 — 最低优先级"""
    print(f"  🧹 后台清理: {target}")
    return {"level": "low", "target": target}


# ── 3. 入口 ──
async def main() -> None:
    print("🚀 Celery 优先级队列示例\n")

    # 优先级说明
    print("── 优先级说明 ──")
    print("  📋 Redis:    优先级 0-9，0 = 最高优先级")
    print("  📋 RabbitMQ: 优先级 0-255，0 = 最低优先级 (与 Redis 相反!)")
    print("  📋 使用真实 broker 时，Worker 会按优先级顺序消费任务")
    print()

    # 使用 apply_async 指定优先级
    print("── 使用 apply_async(priority=N) 调度任务 ──\n")

    # 优先级 0 — 最高 (Redis)
    print("  [priority=0] 最高优先级 — 紧急告警")
    r1 = await asyncio.to_thread(
        critical_alert.apply_async,
        args=("服务器 CPU 100%",),
        priority=0,
    )
    print(f"  ✅ 结果: {await asyncio.to_thread(r1.get, timeout=30)}\n")

    # 优先级 5 — 中等 (默认)
    print("  [priority=5] 中等优先级 — 普通处理")
    r2 = await asyncio.to_thread(
        normal_process.apply_async,
        args=("订单数据同步",),
        priority=5,
    )
    print(f"  ✅ 结果: {await asyncio.to_thread(r2.get, timeout=30)}\n")

    # 优先级 9 — 最低 (Redis)
    print("  [priority=9] 最低优先级 — 后台清理")
    r3 = await asyncio.to_thread(
        background_cleanup.apply_async,
        args=("过期缓存",),
        priority=9,
    )
    print(f"  ✅ 结果: {await asyncio.to_thread(r3.get, timeout=30)}\n")

    # 也可以在任务装饰器中设置默认优先级
    print("── 其他设置优先级的方式 ──")
    print("  💡 @app.task(priority=0)          # 装饰器中设置默认优先级")
    print("  💡 task.apply_async(priority=3)   # 调用时覆盖优先级")
    print("  💡 task.delay() 不支持 priority   # delay() 无法传递优先级参数")
    print()

    # Redis vs RabbitMQ 对比
    print("── Redis vs RabbitMQ 优先级对比 ──")
    comparisons = [
        ("实现方式", "多个 List 模拟", "原生 x-max-priority"),
        ("优先级范围", "0-9 (建议)", "0-255"),
        ("0 的含义", "最高优先级", "最低优先级"),
        ("性能影响", "每个优先级一个 List，轮询开销", "原生支持，开销小"),
        ("严格保证", "近似优先级", "严格优先级"),
    ]
    print(f"  {'特性':<12} {'Redis':<24} {'RabbitMQ':<24}")
    print(f"  {'─' * 12} {'─' * 24} {'─' * 24}")
    for feature, redis_val, rabbit_val in comparisons:
        print(f"  {feature:<12} {redis_val:<24} {rabbit_val:<24}")


if __name__ == "__main__":
    asyncio.run(main())
