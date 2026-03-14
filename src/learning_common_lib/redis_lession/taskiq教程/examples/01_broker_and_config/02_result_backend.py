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
    - broker.with_result_backend() — 为 Broker 绑定结果后端（返回新 Broker）
    - handle.wait_result()     — 阻塞等待任务执行结果
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
    - broker.with_result_backend() 返回的是 **新 Broker**，必须重新赋值
    - result_backend 使用独立的 Redis DB（db=1），与 broker（db=0）隔离
    - TaskiqResult.execution_time 单位为秒（float）
"""

from __future__ import annotations

import asyncio

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

# ── 1. 创建 Broker + ResultBackend ──
# Broker 负责消息传递（db=0），ResultBackend 负责结果存储（db=1）
_broker = ListQueueBroker(url="redis://default:123456@localhost:6379/0")

result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
    result_ex_time=3600,  # 结果过期时间：3600 秒 = 1 小时
)

# ⚠️ 关键：with_result_backend() 返回 **新 Broker**，必须重新赋值！
# 错误写法: _broker.with_result_backend(result_backend)  ← 返回值被丢弃
# 正确写法: broker = _broker.with_result_backend(result_backend)
broker = _broker.with_result_backend(result_backend)


# ── 2. 定义任务 ──


@broker.task
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

    print("🚀 发送任务: add(3, 7)")
    handle = await add.kiq(3, 7)
    print(f"   task_id = {handle.task_id}")
    print()

    # wait_result() 阻塞等待 Worker 执行完成并返回结果
    # timeout 单位为秒，超时抛出 asyncio.TimeoutError
    print("⏳ 等待任务结果...")
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

    await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())