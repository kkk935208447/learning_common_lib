"""
解决什么问题: 提供 async-first 的生产级 TaskIQ 配置对象，统一 broker、结果后端、序列化与并发约定
输入输出约定: TaskiqConfig dataclass 实例即配置项，通过 create_broker() / create_result_backend() 工厂方法创建组件
失败策略: 配置本身不会失败；运行时由 TaskIQ 框架根据配置执行对应的重试/超时策略
不适用场景: 多环境差异化配置建议继承 TaskiqConfig 覆盖字段，或用环境变量注入

配置分组:
  Broker 连接: broker_url
  结果后端: result_backend_url, result_ex_time
  并发与序列化: concurrency, serializer
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend


@dataclass
class TaskiqConfig:
    """生产级 TaskIQ 配置。

    使用方式:
        cfg = TaskiqConfig()
        broker = cfg.create_broker()
    或覆盖字段:
        cfg = TaskiqConfig(broker_url="redis://default:xxx@prod-host:6379/0")
    """

    # --- Broker ---
    broker_url: str = field(
        default_factory=lambda: os.getenv(
            "TASKIQ_BROKER_URL",
            "redis://default:123456@localhost:6379/0",
        ),
    )

    # --- 结果后端 ---
    result_backend_url: str = field(
        default_factory=lambda: os.getenv(
            "TASKIQ_RESULT_BACKEND_URL",
            "redis://default:123456@localhost:6379/1",
        ),
    )
    # 结果过期时间（秒）
    result_ex_time: int = field(
        default_factory=lambda: int(os.getenv("TASKIQ_RESULT_EX_TIME", "3600")),
    )

    # --- 并发 ---
    concurrency: int = field(
        default_factory=lambda: int(os.getenv("TASKIQ_CONCURRENCY", "10")),
    )

    # --- 序列化 ---
    serializer: str = "json"

    # ------------------------------------------------------------------
    # 工厂方法
    # ------------------------------------------------------------------

    def create_broker(self) -> ListQueueBroker:
        """创建 ListQueueBroker 实例，使用当前配置的 broker_url。"""
        return ListQueueBroker(url=self.broker_url)

    def create_result_backend(self) -> RedisAsyncResultBackend:
        """创建 RedisAsyncResultBackend 实例，使用当前配置的 result_backend_url。"""
        return RedisAsyncResultBackend(
            redis_url=self.result_backend_url,
            result_ex_time=self.result_ex_time,
        )


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：打印所有配置项，验证配置值是否符合预期。"""
    cfg = TaskiqConfig()

    print("🔧 === TaskiqConfig 生产配置 ===")
    print(f"  broker_url          = {cfg.broker_url!r}")
    print(f"  result_backend_url  = {cfg.result_backend_url!r}")
    print(f"  result_ex_time      = {cfg.result_ex_time!r}")
    print(f"  concurrency         = {cfg.concurrency!r}")
    print(f"  serializer          = {cfg.serializer!r}")
    print()
    print("✅ 配置加载完成，可通过 cfg.create_broker() / cfg.create_result_backend() 使用")


if __name__ == "__main__":
    _demo()
