"""
TaskIQ RedisAsyncResultBackend 配置与结果获取。

目标:
    演示 RedisAsyncResultBackend 配置与结果获取

关键概念:
    - ResultBackend 存储任务返回值
    - TaskiqResult 结果对象
    - result_ex_time 过期时间（秒）

关键 API:
    - RedisAsyncResultBackend  — 基于 Redis 的异步结果后端
    - broker.with_result_backend() — 为 Broker 绑定结果后端（原地更新并返回自身）
    - handle.wait_result()     — 异步等待任务执行结果
    - TaskiqResult             — 结果对象，包含 return_value / is_err / error / execution_time

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/01_broker_and_config

运行方式:
    Worker:
        taskiq worker examples.01_broker_and_config.02_result_backend:broker
    Client:
        python examples/01_broker_and_config/02_result_backend.py

预期现象:
    - Worker 控制台显示任务接收、执行、结果存储日志
    - Client 显示任务结果：return_value=10, is_err=False, execution_time > 0

生产提醒:
    - result_ex_time 控制结果在 Redis 中的过期时间，避免 Redis 内存无限增长
    - 不需要结果的任务（fire-and-forget）可以不配置 result_backend

技术要点:
    - broker.with_result_backend() 会原地更新 Broker，并返回自身
    - result_backend 使用独立的 Redis DB（db=1），与 broker（db=0）隔离
    - 可通过环境变量 TASKIQ_QUEUE_NAME 覆盖 queue_name，避免不同示例互相抢消息
    - TaskiqResult.execution_time 单位为秒（float）
"""

from __future__ import annotations

import asyncio
import os

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend
from taskiq.serializers import JSONSerializer

QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:examples:01_broker_and_config:02_result_backend",
)

# ── 1. 创建 Broker + ResultBackend ──
# Broker 负责消息传递（db=0），ResultBackend 负责结果存储（db=1）
_broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
)

result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
    result_ex_time=3600,  # 结果过期时间：3600 秒 = 1 小时
    serializer=JSONSerializer()   # taskiq 默认使用的 PickleSerializer序列化，这在 redis 侧是人类不可读的，所以这里使用 JSONSerializer
)

# ⚠️ 关键：with_result_backend() 会原地更新当前 broker，并返回 self。
# 这里继续显式赋值，是为了把“完成结果绑定后的 broker”命名得更清楚。
broker = _broker.with_result_backend(result_backend)


# ── 2. 定义任务 ──

# taskiq 与celery不同，celery task_name有一套完整自动拼接逻辑，而taskiq的自动拼接容易出错。
# TaskIQ 中 task_name 必须在当前 broker 的任务注册表中保持唯一，且 producer / worker 两侧必须完全一致。对于会被直接运行的教程文件，建议显式指定稳定的 task_name，避免脚本作为 __main__ 运行时，默认 task_name 推导受启动方式影响。
# 一套比较万金油的定义 task_name 的方式：模块名.xxx.xxx.模块名.函数名
@broker.task(task_name="examples.01_broker_and_config.02_result_backend.add")
async def add(x: int, y: int) -> int:
    """两数相加，返回结果将存储到 ResultBackend。"""
    print(f"📦 Worker 收到任务: add({x}, {y})")
    result = x + y
    print(f"✅ 计算完成: {x} + {y} = {result}")
    return result


# ── 3. 客户端发送任务并获取结果 ──


async def main() -> None:
    """演示：发送任务并通过 wait_result() 获取结果。"""
    await broker.startup()
    try:
        print("=" * 60)
        print("阶段 1: 给 Broker 绑定 Result Backend")
        print("=" * 60)
        print(f"_broker is broker ? {_broker is broker}")
        print(f"broker.queue_name = {broker.queue_name!r}")
        print("解释:")
        print("  - _broker 只负责消息队列")
        print("  - with_result_backend(...) 会原地更新 broker，并返回 self")
        print("  - 绑定后，这个 broker 同时具备发消息 + 查结果的能力")
        print("  - 当前示例也显式固定了 queue_name，避免和其他教程 worker 互抢")
        print()

        print("🚀 发送任务: add(3, 7)")
        handle = await add.kiq(3, 7)
        print(f"   task_id = {handle.task_id}")
        print()

        # wait_result() 是异步轮询等待结果
        # timeout 单位为秒，超时抛出 TaskiqResultTimeoutError
        print("阶段 2: 轮询 Result Backend，直到结果可用")
        print("⏳ 异步等待任务结果...")
        result = await handle.wait_result(timeout=10)

        # ── 4. 解析 TaskiqResult 对象 ──
        print()
        print("📋 TaskiqResult 详情:")
        print(f"   return_value    = {result.return_value}")    # 任务返回值
        print(f"   is_err          = {result.is_err}")          # 是否执行出错
        print(f"   error           = {result.error}")           # 错误信息（无错误时为 None）
        print(f"   execution_time  = {result.execution_time:.4f}s")  # 执行耗时
        print()

        if not result.is_err:
            print(f"✅ 任务执行成功! 3 + 7 = {result.return_value}")
        else:
            print(f"❌ 任务执行失败: {result.error}")
        print()
        print("对照上一节:")
        print("  - 01_taskiq_hello.py: 只能发任务，不能拿结果")
        print("  - 当前示例: handle.wait_result() 可以拿到完整 TaskiqResult")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
