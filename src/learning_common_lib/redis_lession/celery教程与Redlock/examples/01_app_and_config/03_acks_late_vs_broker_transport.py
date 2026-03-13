"""
目标: 通过真实任务调用讲清 task_acks_late 与 broker_transport_options 的职责边界
关键概念:
  - task_acks_late: 任务确认时机，属于消费语义
  - broker_transport_options: broker 传输层配置，属于消息通道行为
  - 二者经常一起出现，但解决的是不同层级的问题
关键 API: task_acks_late, task_reject_on_worker_lost, broker_transport_options
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/01_app_and_config
运行方式:
  Worker: celery -A examples.01_app_and_config.03_acks_late_vs_broker_transport worker -l info -P solo
  Client: python examples/01_app_and_config/03_acks_late_vs_broker_transport.py
预期现象:
  - 客户端打印 acks_late 与 broker_transport_options 配置
  - Worker 执行任务时也会打印同样的配置和 request 信息
  - 客户端轮询任务状态并拿到最终结果
生产提醒:
  - acks_late 解决不了幂等性问题；任务仍然需要设计成可重复执行
  - transport_options 也不等于可靠消费，它只是 broker 这一层的补充配置
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from celery import Celery, Task


def build_app() -> Celery:
    app = Celery(
        "acks_late_vs_broker_transport",
        broker="redis://:123456@localhost:6379/0",
        backend="redis://:123456@localhost:6379/1",
    )
    app.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        broker_transport_options={
            "visibility_timeout": 1800,
        },
    )
    return app


app = build_app()


@app.task(bind=True, name="examples.acks_late.inspect_runtime")
def inspect_runtime(self: Task, job_name: str, sleep_seconds: int = 2) -> dict[str, Any]:
    """打印 worker 侧配置与 request 信息。"""
    print(f"  📦 开始执行任务: {job_name}")
    print("  acks_late 全局配置:", self.app.conf.task_acks_late)
    print("  broker_transport_options:", self.app.conf.broker_transport_options)
    print("  request.id:", self.request.id)
    print("  request.retries:", self.request.retries)
    print("  request.delivery_info:", self.request.delivery_info)
    time.sleep(sleep_seconds)
    return {
        "job_name": job_name,
        "acks_late": self.app.conf.task_acks_late,
        "visibility_timeout": self.app.conf.broker_transport_options.get("visibility_timeout"),
        "message": "任务执行完成；这里观察到的是运行时配置，而不是静态概念",
    }


async def main() -> None:
    print("🚀 acks_late 与 broker_transport_options 差异示例\n")
    print("── 当前配置 ──")
    print("acks_late 全局配置:", app.conf.task_acks_late)
    print("broker_transport_options:", app.conf.broker_transport_options)
    print()

    print("── 提交任务 ──")
    result = await asyncio.to_thread(
        inspect_runtime.apply_async,
        args=("ack-demo",),
        kwargs={"sleep_seconds": 2},
    )
    print("  task_id:", result.id)
    print("  初始状态:", result.state)
    print()

    print("── 轮询状态 ──")
    for _ in range(10):
        state = result.state
        print("  当前状态:", state)
        if result.ready():
            break
        await asyncio.sleep(0.5)
    print()

    print("── 获取结果 ──")
    value = await asyncio.to_thread(result.get, timeout=20)
    print("  结果:", value)
    await asyncio.to_thread(result.forget)
    print()

    print("── 运行时如何理解这两个配置 ──")
    print("1. task_acks_late 决定 worker 在任务执行前还是执行后 ack。")
    print("2. broker_transport_options 影响 broker 如何管理未确认消息。")
    print("3. 本示例里你能看到它们都进入了运行时，但作用层次不同。")
    print("4. acks_late 是消费语义；visibility_timeout 是 broker 侧补充配置。")


if __name__ == "__main__":
    asyncio.run(main())
