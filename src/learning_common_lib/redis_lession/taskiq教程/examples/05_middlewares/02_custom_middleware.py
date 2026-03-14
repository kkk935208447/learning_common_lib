"""
TaskIQ 自定义中间件 — 执行耗时统计与请求 ID 注入。

目标:
    演示自定义中间件 — 执行耗时统计和请求 ID 注入

关键概念:
    - 自定义中间件实现业务逻辑
    - pre_execute 中注入数据，post_execute 中读取
    - 中间件注册顺序影响执行顺序

关键 API:
    - TaskiqMiddleware                        — 中间件基类
    - broker.with_middlewares(M1(), M2())      — 按顺序注册多个中间件
    - message.labels                           — 消息标签字典，可读写

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/05_middlewares

运行方式:
    Worker:
        taskiq worker examples.05_middlewares.02_custom_middleware:broker
    Client:
        python examples/05_middlewares/02_custom_middleware.py

预期现象:
    - Worker 控制台显示请求 ID 和任务执行耗时
    - Client 控制台显示 pre_send 注入的 request_id

生产提醒:
    - 耗时统计中间件可对接 Prometheus / Datadog 等监控系统
    - request_id 可串联分布式链路追踪（配合 OpenTelemetry）
    - 中间件顺序很重要：RequestIdMiddleware 应在 TimingMiddleware 之前注册

技术要点:
    - 中间件注册顺序影响执行顺序
    - pre_send 在 client 侧执行，适合注入 request_id
    - pre_execute / post_execute 在 worker 侧执行，适合做耗时统计
    - labels 是 dict[str, str]，值必须是字符串
"""

from __future__ import annotations

import asyncio
import time
import uuid

from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

# ── 1. 请求 ID 注入中间件 ──


class RequestIdMiddleware(TaskiqMiddleware):
    """在 client 侧为每条消息注入唯一 request_id，便于链路追踪。"""

    async def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        """发送前注入 request_id（如果调用方未手动指定）。"""
        if "request_id" not in message.labels:
            message.labels["request_id"] = str(uuid.uuid4())
        print(f"🔖 [RequestId] 注入 request_id={message.labels['request_id']}")
        return message

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Worker 侧打印 request_id，方便日志关联。"""
        request_id = message.labels.get("request_id", "N/A")
        print(f"🔖 [RequestId] Worker 收到任务, request_id={request_id}")
        return message


# ── 2. 执行耗时统计中间件 ──


class TimingMiddleware(TaskiqMiddleware):
    """在 worker 侧统计任务执行耗时。"""

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """执行前记录开始时间到 labels。"""
        message.labels["_timing_start"] = str(time.monotonic())
        print(f"⏱️ [Timing] 开始计时: {message.task_name}")
        return message

    async def post_execute(
        self, message: TaskiqMessage, result: TaskiqResult
    ) -> None:
        """执行后计算耗时并打印。"""
        start = float(message.labels.get("_timing_start", "0"))
        elapsed = time.monotonic() - start
        print(f"⏱️ [Timing] 执行耗时: {elapsed:.4f}s ({message.task_name})")


# ── 3. 创建 Broker + 注册中间件（顺序很重要） ──
# RequestIdMiddleware 先注册 → 先执行 pre_send，确保 request_id 在 Timing 之前就位
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
).with_result_backend(result_backend).with_middlewares(
    RequestIdMiddleware(),
    TimingMiddleware(),
)


# ── 4. 定义任务 ──


@broker.task
async def slow_add(x: int, y: int) -> int:
    """模拟耗时计算任务。"""
    print(f"📦 Worker 正在执行: slow_add({x}, {y})")
    await asyncio.sleep(0.5)  # 模拟耗时操作
    result = x + y
    print(f"✅ 计算完成: {x} + {y} = {result}")
    return result


# ── 5. 客户端发送任务 ──


async def main() -> None:
    """发送任务，观察 request_id 注入和耗时统计。"""
    await broker.startup()

    print("🚀 发送任务: slow_add(10, 20)")
    print("=" * 50)

    # 方式 1: 自动生成 request_id
    handle = await slow_add.kiq(10, 20)
    print(f"✅ 任务已发送! task_id={handle.task_id}")
    print()

    # 方式 2: 手动指定 request_id（适合从上游服务传递）
    print("🚀 发送任务: slow_add(30, 40) — 手动指定 request_id")
    handle2 = await slow_add.kicker().with_labels(
        request_id="my-custom-req-001",
    ).kiq(30, 40)
    print(f"✅ 任务已发送! task_id={handle2.task_id}")
    print()

    print("💡 中间件执行顺序:")
    print("   注册顺序: RequestIdMiddleware → TimingMiddleware")
    print("   pre_send:    RequestId.pre_send → Timing.pre_send(未定义,跳过)")
    print("   pre_execute: RequestId.pre_execute → Timing.pre_execute")
    print("   post_execute: RequestId.post_execute(未定义) → Timing.post_execute")

    await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())