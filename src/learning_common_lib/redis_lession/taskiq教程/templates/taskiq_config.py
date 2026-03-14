"""
解决什么问题: 提供 async-first 的生产级 TaskIQ 配置对象，统一 broker 与结果后端约定
输入输出约定: TaskiqConfig dataclass 实例即配置项，通过 create_broker() / create_result_backend() 工厂方法创建组件
失败策略: 配置本身不会失败；运行时由 TaskIQ 框架根据 broker/result_backend 配置执行
不适用场景: worker 进程数、threadpool/process pool 这类运行参数应放到 taskiq worker CLI，而不是 Broker 配置对象里

配置分组:
  Broker 连接: broker_url, queue_name
  结果后端: result_backend_url, result_ex_time
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
    queue_name: str = field(
        default_factory=lambda: os.getenv(
            "TASKIQ_QUEUE_NAME",
            "taskiq:default",
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

    # ------------------------------------------------------------------
    # 工厂方法
    # ------------------------------------------------------------------

    def create_broker(self) -> ListQueueBroker:
        """创建 ListQueueBroker 实例，使用当前配置的 broker_url 和 queue_name。"""
        return ListQueueBroker(
            url=self.broker_url,
            queue_name=self.queue_name,
        )

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
    print(f"  queue_name          = {cfg.queue_name!r}")
    print(f"  result_backend_url  = {cfg.result_backend_url!r}")
    print(f"  result_ex_time      = {cfg.result_ex_time!r}")
    print()
    print("✅ 配置加载完成，可通过 cfg.create_broker() / cfg.create_result_backend() 使用")


if __name__ == "__main__":
    _demo()
