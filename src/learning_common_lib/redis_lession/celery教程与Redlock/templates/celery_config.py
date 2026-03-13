"""
解决什么问题: 提供生产级 Celery 配置对象，统一序列化、超时、并发、限流、可靠投递等关键参数
输入输出约定: CeleryConfig 类属性即配置项，直接传给 app.config_from_object(CeleryConfig)
失败策略: 配置本身不会失败；运行时由 Celery 框架根据配置执行对应的超时/重试/拒绝策略
不适用场景: 多环境差异化配置建议继承 CeleryConfig 覆盖属性，或用环境变量注入

配置分组:
  序列化与时区: accept_content, task_serializer, result_serializer, timezone, enable_utc
  超时与限流: task_soft_time_limit, task_time_limit, task_default_rate_limit
  Broker 传输层: broker_transport_options
  连接池与结果: broker_pool_limit, result_expires
  并发与预取: worker_concurrency, worker_prefetch_multiplier
  可靠投递: task_acks_late, task_reject_on_worker_lost
"""

from __future__ import annotations

import os


class CeleryConfig:
    """生产级 Celery 配置。

    使用方式:
        app.config_from_object(CeleryConfig)
    或继承后覆盖:
        class DevConfig(CeleryConfig):
            broker_url = "redis://:mypassword@localhost:6379/0"
    """

    # --- Broker / Backend ---
    broker_url: str = os.getenv(
        "CELERY_BROKER_URL",
        "redis://:123456@localhost:6379/0",
    )
    result_backend: str = os.getenv(
        "CELERY_RESULT_BACKEND",
        "redis://:123456@localhost:6379/1",
    )
    redis_lock_url: str = os.getenv(
        "REDIS_LOCK_URL",
        "redis://:123456@localhost:6379/2"
    )

    # --- 序列化与时区 ---
    accept_content: list[str] = ["json"]
    task_serializer: str = "json"
    result_serializer: str = "json"
    timezone: str = "Asia/Shanghai"
    enable_utc: bool = True

    # --- 超时 ---
    # soft_time_limit 触发 SoftTimeLimitExceeded，任务可捕获做清理
    # time_limit 是硬杀，worker 直接终止任务进程
    task_soft_time_limit: int = 300   # 5 分钟
    task_time_limit: int = 600        # 10 分钟

    # --- 限流 ---
    task_default_rate_limit: str = "100/m"  # 每分钟 100 次

    # --- 连接池与结果 ---
    # visibility_timeout 影响未确认消息多久后重新对其他 worker 可见，
    # 它是 broker 传输层配置，不替代 task_acks_late。
    broker_transport_options: dict[str, int] = {
        "visibility_timeout": 3600,
    }
    broker_pool_limit: int = 10       # Broker 连接池上限
    result_expires: int = 3600        # 结果过期时间（秒）

    # --- 并发与预取 ---
    worker_concurrency: int = int(os.getenv("CELERY_CONCURRENCY", "4"))
    worker_prefetch_multiplier: int = 1  # 公平调度，每次只预取 1 条

    # --- 可靠投递 ---
    # acks_late: 任务执行完才确认，worker 崩溃时消息回到队列
    # reject_on_worker_lost: worker 异常退出时拒绝消息（配合 acks_late）
    task_acks_late: bool = True
    task_reject_on_worker_lost: bool = True


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：打印所有配置项，验证配置值是否符合预期。"""
    print("🔧 === CeleryConfig 生产配置 ===")
    for attr in sorted(dir(CeleryConfig)):
        if attr.startswith("_"):
            continue
        value = getattr(CeleryConfig, attr)
        if callable(value):
            continue
        print(f"  {attr} = {value!r}")

    print()
    print("✅ 配置加载完成，可通过 app.config_from_object(CeleryConfig) 使用")


if __name__ == "__main__":
    _demo()
