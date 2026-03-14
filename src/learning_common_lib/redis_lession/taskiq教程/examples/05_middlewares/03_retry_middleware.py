"""
TaskIQ 指数退避重试中间件 — 在 on_error 中实现自动重试。

目标:
    演示指数退避重试中间件的实现

关键概念:
    - 在 on_error 中判断异常类型决定是否重试
    - 指数退避 + 抖动避免惊群效应
    - 通过 labels 配置 max_retries 和 retry_delay

关键 API:
    - TaskiqMiddleware.on_error         — 任务异常时触发的钩子
    - broker.formatter.dumps(message)   — 先序列化成 BrokerMessage
    - broker.kick(...)                  — 重新发送消息到队列
    - message.labels                    — 存储重试计数和配置

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/05_middlewares

运行方式:
    Worker:
        taskiq worker examples.05_middlewares.03_retry_middleware:broker
    Client:
        python examples/05_middlewares/03_retry_middleware.py

预期现象:
    - Worker 控制台显示前 2 次执行失败并触发重试
    - 第 3 次执行成功，任务最终完成
    - 每次重试间隔递增（指数退避）

生产提醒:
    - 仅对可重试异常（网络超时、限流等）进行重试，业务逻辑错误不应重试
    - 设置合理的 max_retries 上限，避免无限重试耗尽资源
    - 退避上限建议不超过 60s，配合死信队列处理最终失败

技术要点:
    - on_error 钩子在任务抛出异常时触发
    - broker.kick(broker.formatter.dumps(message)) 重新发送消息到队列
    - 退避公式: delay = base * 2^retry_count + random(0, 1)
    - labels 中的值必须是字符串类型
"""

from __future__ import annotations

import asyncio
import random

from taskiq import Context, TaskiqDepends, TaskiqMessage, TaskiqMiddleware, TaskiqResult
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

# ── 1. 可重试异常定义 ──


class RetryableError(Exception):
    """标记为可重试的异常基类。只有此类异常才会触发自动重试。"""


class TemporaryNetworkError(RetryableError):
    """模拟临时网络错误 — 可重试。"""


# ── 2. 指数退避重试中间件 ──


class RetryMiddleware(TaskiqMiddleware):
    """
    指数退避重试中间件。

    工作原理:
        1. on_error 捕获异常，判断是否为 RetryableError
        2. 从 labels 读取 max_retries（默认 3）和 retry_delay（默认 1.0s）
        3. 计算退避时间: delay = base * 2^count + random(0, 1)
        4. 等待退避时间后，通过 broker.kick() 重新入队
    """

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult,
        error: BaseException,
    ) -> None:
        """任务异常时判断是否重试。"""
        # 仅对 RetryableError 子类进行重试
        if not isinstance(error, RetryableError):
            print(f"🔴 [Retry] 不可重试异常，放弃: {type(error).__name__}: {error}")
            return

        # 从 labels 读取重试配置
        max_retries = int(message.labels.get("max_retries", "3"))
        base_delay = float(message.labels.get("retry_delay", "1.0"))
        retry_count = int(message.labels.get("_retry_count", "0"))

        if retry_count >= max_retries:
            print(
                f"🔴 [Retry] 重试次数已耗尽 ({retry_count}/{max_retries})，"
                f"最终失败: {error}"
            )
            return

        # 计算指数退避 + 随机抖动
        backoff = base_delay * (2 ** retry_count) + random.random()
        retry_count += 1
        message.labels["_retry_count"] = str(retry_count)

        print(
            f"🔄 [Retry] 第 {retry_count}/{max_retries} 次重试，"
            f"退避 {backoff:.2f}s 后重新入队..."
        )
        await asyncio.sleep(backoff)

        # 重新发送消息到队列
        serialized_message = self.broker.formatter.dumps(message)
        await self.broker.kick(serialized_message)


# ── 3. 创建 Broker + 注册重试中间件 ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
).with_result_backend(result_backend).with_middlewares(
    RetryMiddleware(),
)

# ── 4. 模拟不稳定任务 ──
# 通过 message.labels["_retry_count"] 推导当前尝试次数，避免多进程下的全局计数失真


@broker.task
async def unstable_task(
    item: str,
    context: Context = TaskiqDepends(),
) -> str:
    """
    不稳定任务 — 前 2 次抛出 TemporaryNetworkError，第 3 次成功。

    用于演示重试中间件的退避重试行为。
    """
    retry_count = int(context.message.labels.get("_retry_count", "0"))
    attempt = retry_count + 1

    print(f"📦 Worker 执行 unstable_task({item!r})，第 {attempt} 次调用")

    if attempt <= 2:
        raise TemporaryNetworkError(
            f"模拟网络超时（第 {attempt} 次）"
        )

    result = f"处理完成: {item}"
    print(f"✅ 任务成功: {result}")
    return result


# ── 5. 客户端发送任务 ──


async def main() -> None:
    """发送不稳定任务，观察重试中间件的退避重试行为。"""
    await broker.startup()
    try:
        print("🚀 发送不稳定任务: unstable_task('重要数据')")
        print("=" * 50)

        # 通过 labels 配置重试参数
        handle = await unstable_task.kicker().with_labels(
            max_retries="3",
            retry_delay="0.5",
        ).kiq("重要数据")

        result = await handle.wait_result(timeout=20)
        print(f"✅ 任务已发送! task_id={handle.task_id}")
        print(f"✅ 最终结果   = {result.return_value}")
        print()
        print("💡 重试行为说明:")
        print("   第 1 次执行: 失败 → 退避 0.5 * 2^0 + jitter ≈ 0.5~1.5s → 重试")
        print("   第 2 次执行: 失败 → 退避 0.5 * 2^1 + jitter ≈ 1.0~2.0s → 重试")
        print("   第 3 次执行: 成功 ✅")
        print()
        print("💡 退避公式: delay = base_delay * 2^retry_count + random(0, 1)")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
