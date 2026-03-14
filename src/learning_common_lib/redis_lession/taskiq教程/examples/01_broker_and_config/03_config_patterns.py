"""
TaskIQ 配置模式 — 环境变量覆盖、builder 链式调用。

目标:
    演示 TaskIQ 配置模式 — 环境变量覆盖、builder 链式调用

关键概念:
    - 环境变量覆盖 broker_url
    - 链式 .with_result_backend().with_middlewares()
    - 配置与任务定义分离

关键 API:
    - ListQueueBroker          — 基于 Redis List 的消息队列 Broker
    - RedisAsyncResultBackend  — 基于 Redis 的异步结果后端
    - broker.with_result_backend() — 链式绑定结果后端
    - broker.with_middlewares()    — 链式绑定中间件

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/01_broker_and_config

运行方式:
    python examples/01_broker_and_config/03_config_patterns.py
    （纯配置演示，不需要 Worker）

预期现象:
    - 打印三种配置模式的 Broker 信息
    - 展示环境变量覆盖、链式调用、配置汇总

生产提醒:
    - 生产环境务必通过环境变量注入 Redis 密码，不要硬编码
    - 建议将 Broker 配置集中到一个模块，其他模块 import 使用

技术要点:
    - os.getenv() 提供默认值，开发环境零配置即可运行
    - 链式调用每一步都返回新对象，最终赋值给 broker
    - with_middlewares() 接受可变参数，可一次注册多个中间件
"""

from __future__ import annotations

import os

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

# ── 1. 模式一：环境变量覆盖 ──
# 开发环境使用默认值，生产环境通过环境变量注入
BROKER_URL = os.getenv("TASKIQ_BROKER_URL", "redis://default:123456@localhost:6379/0")
RESULT_BACKEND_URL = os.getenv(
    "TASKIQ_RESULT_BACKEND_URL",
    "redis://default:123456@localhost:6379/1",
)
RESULT_EX_TIME = int(os.getenv("TASKIQ_RESULT_EX_TIME", "3600"))


def create_broker_from_env() -> ListQueueBroker:
    """从环境变量创建 Broker（推荐生产用法）。"""
    backend = RedisAsyncResultBackend(
        redis_url=RESULT_BACKEND_URL,
        result_ex_time=RESULT_EX_TIME,
    )
    broker = ListQueueBroker(url=BROKER_URL).with_result_backend(backend)
    return broker


# ── 2. 模式二：Builder 链式调用 ──
# 一行完成 Broker + ResultBackend + Middlewares 组装


def create_broker_chained() -> ListQueueBroker:
    """链式调用一步到位（适合简单项目）。"""
    broker = (
        ListQueueBroker(url="redis://default:123456@localhost:6379/0")
        .with_result_backend(
            RedisAsyncResultBackend(
                redis_url="redis://default:123456@localhost:6379/1",
                result_ex_time=3600,
            )
        )
        # .with_middlewares(MyMiddleware())  # 按需添加中间件
    )
    return broker


# ── 3. 模式三：配置类集中管理 ──


class TaskiqSettings:
    """TaskIQ 配置集中管理（适合中大型项目）。"""

    def __init__(
        self,
        broker_url: str = "redis://default:123456@localhost:6379/0",
        result_url: str = "redis://default:123456@localhost:6379/1",
        result_ex_time: int = 3600,
    ) -> None:
        self.broker_url = broker_url
        self.result_url = result_url
        self.result_ex_time = result_ex_time

    def create_broker(self) -> ListQueueBroker:
        """根据配置创建完整的 Broker 实例。"""
        backend = RedisAsyncResultBackend(
            redis_url=self.result_url,
            result_ex_time=self.result_ex_time,
        )
        return ListQueueBroker(url=self.broker_url).with_result_backend(backend)

    def summary(self) -> str:
        """返回配置摘要字符串。"""
        return (
            f"broker_url     = {self.broker_url}\n"
            f"result_url     = {self.result_url}\n"
            f"result_ex_time = {self.result_ex_time}s"
        )


# ── 4. 演示 ──


def main() -> None:
    """演示三种配置模式。"""
    print("=" * 60)
    print("🚀 TaskIQ 配置模式演示")
    print("=" * 60)
    print()

    # 模式一：环境变量
    print("── 模式一：环境变量覆盖 ──")
    print(f"   BROKER_URL       = {BROKER_URL}")
    print(f"   RESULT_BACKEND   = {RESULT_BACKEND_URL}")
    print(f"   RESULT_EX_TIME   = {RESULT_EX_TIME}s")
    broker_env = create_broker_from_env()
    print(f"   broker           = {broker_env!r}")
    print()

    # 模式二：链式调用
    print("── 模式二：Builder 链式调用 ──")
    broker_chain = create_broker_chained()
    print(f"   broker           = {broker_chain!r}")
    print()

    # 模式三：配置类
    print("── 模式三：配置类集中管理 ──")
    settings = TaskiqSettings()
    print(f"   {settings.summary()}")
    broker_cls = settings.create_broker()
    print(f"   broker           = {broker_cls!r}")
    print()

    print("✅ 三种配置模式演示完成")
    print()
    print("💡 生产建议:")
    print("   - 小项目 → 模式二（链式调用，简洁直观）")
    print("   - 中大型项目 → 模式三（配置类，便于测试和切换环境）")
    print("   - 所有环境 → 敏感信息（密码）通过环境变量注入")


if __name__ == "__main__":
    main()
