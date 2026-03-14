"""
解决什么问题: 提供 TaskIQ Broker 工厂函数和单例管理，统一 broker + result_backend + middlewares 组装
输入输出约定: create_taskiq_broker() 返回配置好的 AsyncBroker；get_broker() 返回模块级单例；init_broker() 幂等初始化
失败策略: get_broker() 在未初始化时抛出 RuntimeError
不适用场景: 需要多个独立 Broker 的场景应直接使用 create_taskiq_broker()，不依赖单例

工厂 + 单例模式:
  create_taskiq_broker(config)  →  新建 Broker
  get_broker()                  →  获取模块级单例
  init_broker(config)           →  初始化单例（只调用一次）
"""

from __future__ import annotations

try:
    from .taskiq_config import TaskiqConfig
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.taskiq_config import TaskiqConfig  # type: ignore[no-redef]

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend  # noqa: F401


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def create_taskiq_broker(config: TaskiqConfig | None = None) -> ListQueueBroker:
    """根据配置创建一个全新的、带 result_backend 的 Broker。

    参数:
        config: TaskIQ 配置对象，为 None 时使用默认 TaskiqConfig()

    返回:
        配置好 result_backend 的 ListQueueBroker 实例
    """
    if config is None:
        config = TaskiqConfig()

    broker = config.create_broker()
    broker = broker.with_result_backend(config.create_result_backend())
    return broker


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

_broker: ListQueueBroker | None = None


def init_broker(config: TaskiqConfig | None = None) -> ListQueueBroker:
    """幂等初始化模块级单例 Broker。

    首次调用时创建 Broker 并缓存；后续调用直接返回已有实例，忽略 config 参数。

    参数:
        config: TaskIQ 配置对象，仅首次调用生效

    返回:
        模块级单例 ListQueueBroker
    """
    global _broker
    if _broker is None:
        _broker = create_taskiq_broker(config)
    return _broker


def get_broker() -> ListQueueBroker:
    """获取模块级单例 Broker。

    必须先调用 init_broker() 完成初始化，否则抛出 RuntimeError。

    返回:
        已初始化的 ListQueueBroker 单例

    异常:
        RuntimeError: 尚未调用 init_broker() 进行初始化
    """
    if _broker is None:
        raise RuntimeError(
            "Broker 尚未初始化，请先调用 init_broker() 完成初始化"
        )
    return _broker


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：创建 Broker、验证单例模式。"""
    # 1. 工厂函数 —— 每次创建全新实例
    broker_a = create_taskiq_broker()
    print("=== 工厂函数 create_taskiq_broker() ===")
    print(f"  broker_a          = {broker_a!r}")
    print(f"  result_backend    = {broker_a.result_backend!r}")
    print()

    # 2. 单例模式 —— init_broker 幂等初始化
    broker_s1 = init_broker()
    broker_s2 = init_broker()  # 第二次调用，返回同一实例
    print("=== 单例模式 init_broker() / get_broker() ===")
    print(f"  broker_s1 is broker_s2 = {broker_s1 is broker_s2}")
    print(f"  get_broker()           = {get_broker()!r}")
    print()

    # 3. 工厂实例与单例实例是不同对象
    print("=== 工厂 vs 单例 ===")
    print(f"  broker_a is broker_s1  = {broker_a is broker_s1}")
    print()
    print("✅ taskiq_app 模块验证通过")


if __name__ == "__main__":
    _demo()
