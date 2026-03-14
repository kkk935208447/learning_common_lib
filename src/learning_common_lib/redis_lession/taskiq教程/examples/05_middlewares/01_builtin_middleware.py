"""
TaskIQ 内置中间件基类与 6 个钩子方法 — 理解中间件生命周期。

目标:
    演示 TaskiqMiddleware 基类和 6 个钩子方法

关键概念:
    - TaskiqMiddleware 是所有中间件的基类
    - 6 个钩子：pre_send / post_send / pre_execute / post_execute / on_error / post_save
    - 中间件在 broker 级别注册，对所有任务生效

关键 API:
    - TaskiqMiddleware                — 中间件基类，继承后重写钩子方法
    - pre_send(message)               — 任务发送前（client 侧）
    - post_send(message, result)      — 任务发送后（client 侧）
    - pre_execute(message)            — 任务执行前（worker 侧）
    - post_execute(message, result)   — 任务执行后（worker 侧）
    - on_error(message, result, error)— 任务异常时（worker 侧）
    - post_save(message, result)      — 结果保存后（worker 侧）

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/05_middlewares

运行方式:
    Worker:
        taskiq worker examples.05_middlewares.01_builtin_middleware:broker
    Client:
        python examples/05_middlewares/01_builtin_middleware.py

预期现象:
    - Worker 控制台显示每个钩子的触发日志
    - Client 控制台显示 pre_send 和 post_send 的触发日志
    - 正常任务触发顺序: pre_execute → post_execute → post_save
    - 异常任务触发顺序: pre_execute → on_error → post_save

生产提醒:
    - 中间件适合做横切关注点：日志、监控、鉴权、限流等
    - 避免在中间件中做重计算，会影响所有任务的吞吐量
    - 中间件异常会导致任务执行失败，务必做好异常处理

技术要点:
    - pre_send/post_send 在 client 侧执行（发送任务时）
    - pre_execute/post_execute/on_error/post_save 在 worker 侧执行
    - 中间件按注册顺序执行
    - pre_send 和 pre_execute 必须返回 message（可修改后返回）
"""

from __future__ import annotations

import asyncio

from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

# ── 1. 自定义日志中间件 — 重写全部 6 个钩子 ──


class SimpleLogMiddleware(TaskiqMiddleware):
    """简单日志中间件 — 在每个钩子中打印触发信息，帮助理解生命周期。"""

    async def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        """任务发送前（client 侧）。必须返回 message，可在此修改消息。"""
        print(f"🔵 [pre_send] 即将发送任务: {message.task_name}")
        return message

    async def post_send(
        self, message: TaskiqMessage, result: TaskiqResult
    ) -> None:
        """任务发送后（client 侧）。无需返回值。"""
        print(f"🟢 [post_send] 任务已发送: {message.task_name}")

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """任务执行前（worker 侧）。必须返回 message，可在此修改消息。"""
        print(f"🟡 [pre_execute] Worker 即将执行: {message.task_name}")
        return message

    async def post_execute(
        self, message: TaskiqMessage, result: TaskiqResult
    ) -> None:
        """任务执行后（worker 侧）。可读取执行结果。"""
        print(
            f"🟣 [post_execute] 执行完成: {message.task_name}, "
            f"is_err={result.is_err}"
        )

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult,
        error: BaseException,
    ) -> None:
        """任务异常时（worker 侧）。仅在任务抛出异常时触发。"""
        print(f"🔴 [on_error] 任务异常: {message.task_name}, error={error}")

    async def post_save(
        self, message: TaskiqMessage, result: TaskiqResult
    ) -> None:
        """结果保存后（worker 侧）。在 result_backend 保存结果之后触发。"""
        print(f"⚪ [post_save] 结果已保存: {message.task_name}")


# ── 2. 创建 Broker + Result Backend + 注册中间件 ──
# with_middlewares() 返回新 broker 实例，不修改原 broker
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
).with_result_backend(result_backend).with_middlewares(
    SimpleLogMiddleware(),
)


# ── 3. 定义任务 ──


@broker.task
async def say_hello(name: str) -> str:
    """简单问候任务 — 用于触发中间件钩子。"""
    print(f"📦 Worker 正在执行: say_hello({name!r})")
    return f"Hello, {name}!"


# ── 4. 客户端发送任务 ──


async def main() -> None:
    """发送任务，观察 client 侧钩子（pre_send / post_send）的触发。"""
    await broker.startup()

    print("🚀 发送任务: say_hello('TaskIQ')")
    print("=" * 50)

    handle = await say_hello.kiq("TaskIQ")

    print("=" * 50)
    print(f"✅ 任务已发送! task_id={handle.task_id}")
    print()
    print("💡 钩子执行顺序说明:")
    print("   Client 侧: pre_send → [发送到队列] → post_send")
    print("   Worker 侧: pre_execute → [执行任务] → post_execute → post_save")
    print("   异常情况:   pre_execute → [执行任务] → on_error → post_save")

    await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())