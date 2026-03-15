"""
TaskIQ 智能重试策略 — 结合中间件 + labels 实现指数退避重试。

目标:
    演示结合中间件 + labels 实现智能重试策略

关键概念:
    - 通过 labels 配置 max_retries / retry_delay
    - 指数退避 + 抖动（jitter）
    - 异常分类决定是否重试

关键 API:
    - @broker.task(max_retries=3, retry_delay=1.0)  — 通过 labels 配置重试参数
    - TaskiqMiddleware.on_error                      — 异常钩子，实现重试逻辑
    - message.labels                                 — 读取任务标签中的重试配置

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/06_error_handling

运行方式:
    Worker:
        taskiq worker examples.06_error_handling.02_smart_retry_with_backoff:broker
    Client:
        python examples/06_error_handling/02_smart_retry_with_backoff.py

预期现象:
    - Worker 收到可重试异常时，按指数退避延迟后重新发送任务
    - Worker 收到致命异常时，直接标记失败，不重试
    - 每次重试的延迟递增: base * 2^count + jitter

生产提醒:
    - 重试次数和延迟应根据业务场景合理配置
    - 指数退避避免雪崩效应，jitter 避免重试风暴
    - 致命异常（参数错误、权限不足等）不应重试

技术要点:
    - labels 中的 max_retries/retry_delay 由中间件读取
    - 退避公式: delay = base_delay * 2^count + random(0, 1)
    - 可重试异常才触发重试，致命异常直接失败
"""

from __future__ import annotations

import asyncio
import os

from taskiq import Context, TaskiqDepends, TaskiqMessage, TaskiqMiddleware, TaskiqResult
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:examples:06_error_handling:02_smart_retry_with_backoff",
)


# ── 1. 自定义异常分类 ──


class RetryableError(Exception):
    """可重试异常 — 临时故障，值得重试。"""


class FatalError(Exception):
    """致命异常 — 不可恢复，不应重试。"""


# ── 2. 智能重试中间件 ──


class SmartRetryMiddleware(TaskiqMiddleware):
    """智能重试中间件 — 读取 labels 配置，实现指数退避 + 异常分类重试。

    工作原理:
        1. 从 message.labels 读取 max_retries / retry_delay
        2. 判断异常类型：可重试 vs 致命
        3. 可重试异常：计算退避延迟，重新发送任务
        4. 致命异常：直接放弃，不重试
    """

    # 定义可重试的异常类型
    RETRYABLE_EXCEPTIONS = (RetryableError, ConnectionError, TimeoutError)

    @staticmethod
    def _jitter(task_id: str) -> float:
        """基于 task_id 计算稳定 jitter，方便教学和 smoke 复现。"""
        checksum = sum(task_id.encode("utf-8")) % 4
        return 0.05 * (checksum + 1)

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult,
        error: BaseException,
    ) -> None:
        """任务异常时触发 — 决定是否重试。"""
        # 读取 labels 中的重试配置
        max_retries = int(message.labels.get("max_retries", "0"))
        base_delay = float(message.labels.get("retry_delay", "1.0"))
        retry_count = int(message.labels.get("_retry_count", "0"))

        task_name = message.task_name
        print(f"🔴 [on_error] 任务异常: {task_name}, error={error!r}")
        print(f"   重试配置: max_retries={max_retries}, retry_count={retry_count}")

        # 致命异常 → 不重试
        if not isinstance(error, self.RETRYABLE_EXCEPTIONS):
            print(f"💀 [致命异常] 不可重试，直接失败: {task_name}")
            return

        # 超过最大重试次数 → 放弃
        if retry_count >= max_retries:
            print(f"💀 [重试耗尽] 已重试 {retry_count} 次，放弃: {task_name}")
            return

        # 计算指数退避延迟: base * 2^count + jitter
        delay = base_delay * (2 ** retry_count) + self._jitter(message.task_id)
        new_count = retry_count + 1
        print(
            f"🔄 [重试] 第 {new_count}/{max_retries} 次重试，"
            f"延迟 {delay:.2f}s: {task_name}"
        )

        # 等待退避延迟
        await asyncio.sleep(delay)

        # 重新发送原始消息，保持同一个 task_id，便于 client 继续 wait_result()
        message.labels["_retry_count"] = str(new_count)
        serialized_message = self.broker.formatter.dumps(message)
        await self.broker.kick(serialized_message)
        print(f"✅ [重试] 任务已重新入队: {task_name}")


# ── 3. 创建 Broker + Result Backend + 注册中间件 ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
).with_result_backend(result_backend).with_middlewares(
    SmartRetryMiddleware(),
)


# ── 4. 定义任务（通过 labels 配置重试策略） ──


@broker.task(
    task_name="examples.06_error_handling.02_smart_retry_with_backoff.fetch_external_api",
    max_retries=3,
    retry_delay=0.4,
)
async def fetch_external_api(
    url: str,
    context: Context = TaskiqDepends(),
) -> dict:
    """调用外部 API — 前两次失败，第三次成功。"""
    retry_count = int(context.message.labels.get("_retry_count", "0"))
    attempt = retry_count + 1
    print(f"📦 Worker 调用外部 API: {url} | attempt={attempt}")
    if attempt <= 2:
        raise RetryableError(f"连接超时: {url} (attempt={attempt})")
    return {"url": url, "status": 200, "data": "ok", "attempt": attempt}


@broker.task(
    task_name="examples.06_error_handling.02_smart_retry_with_backoff.process_payment",
    max_retries=4,
    retry_delay=0.3,
)
async def process_payment(
    order_id: int,
    amount: float,
    context: Context = TaskiqDepends(),
) -> dict:
    """处理支付 — 第一次失败，第二次成功。"""
    retry_count = int(context.message.labels.get("_retry_count", "0"))
    attempt = retry_count + 1
    print(
        f"📦 Worker 处理支付: order_id={order_id}, amount={amount} | attempt={attempt}"
    )
    if attempt == 1:
        raise RetryableError("支付网关繁忙，请稍后重试")
    return {
        "order_id": order_id,
        "amount": amount,
        "status": "paid",
        "attempt": attempt,
    }


@broker.task(
    task_name="examples.06_error_handling.02_smart_retry_with_backoff.validate_data",
    max_retries=3,
    retry_delay=1.0,
)
async def validate_data(data: dict) -> dict:
    """校验数据 — 格式错误是致命异常，不应重试。"""
    print(f"📦 Worker 校验数据: {data}")
    if "name" not in data:
        raise FatalError("缺少必填字段: name（致命错误，不重试）")
    return {"data": data, "valid": True}


# ── 5. 客户端发送任务 ──


async def main() -> None:
    """演示：发送不同场景的任务，观察智能重试行为。"""
    await broker.startup()
    try:
        print("=" * 60)
        print("阶段 1: Worker 先按异常类型判断是否值得重试")
        print("阶段 2: 对可重试异常执行指数退避，再把原消息重新入队")
        print("阶段 3: 保持同一个 task_id，让 client 可以继续 wait_result()")
        print("=" * 60)

        # 场景 1: 可重试异常（网络超时）
        print("🚀 场景 1 — 调用外部 API（可能触发可重试异常）")
        h1 = await fetch_external_api.kiq(url="https://api.example.com/data")
        print(f"   task_id = {h1.task_id}")
        r1 = await h1.wait_result(timeout=20)
        print(f"   最终结果 = {r1.return_value}")
        print()

        # 场景 2: 可重试异常（支付网关繁忙）
        print("🚀 场景 2 — 处理支付（可能触发可重试异常）")
        h2 = await process_payment.kiq(order_id=2001, amount=199.99)
        print(f"   task_id = {h2.task_id}")
        r2 = await h2.wait_result(timeout=20)
        print(f"   最终结果 = {r2.return_value}")
        print()

        # 场景 3: 致命异常（数据格式错误）
        print("🚀 场景 3 — 校验数据（触发致命异常，不重试）")
        h3 = await validate_data.kiq(data={"age": 25})
        print(f"   task_id = {h3.task_id}")
        r3 = await h3.wait_result(timeout=10)
        print(f"   is_err = {r3.is_err}")
        print(f"   error  = {r3.error}")
        print()

        print("对照结论:")
        print("  - labels 中的 max_retries/retry_delay 由 SmartRetryMiddleware 读取")
        print("  - 退避公式: delay = base_delay * 2^count + jitter")
        print("  - RetryableError -> 指数退避重试; FatalError -> 直接失败")
        print("  - 对比 Celery: Celery 常用 self.retry(exc=e, countdown=delay)")
        print("  - TaskIQ 更适合把重试策略收敛到 middleware 中统一治理")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
