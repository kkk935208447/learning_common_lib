"""
@broker.task 基本装饰与任务定义模式。

目标:
    演示 @broker.task 基本装饰与任务定义模式

关键概念:
    - task_name 显式指定
    - 参数类型注解
    - async def 任务

关键 API:
    - @broker.task                    — 默认装饰，task_name 自动生成
    - @broker.task(task_name="...")   — 显式指定 task_name
    - task.kiq()                      — 异步发送任务
    - handle.wait_result()            — 等待任务结果

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/02_task_definition

运行方式:
    Worker:
        taskiq worker examples.02_task_definition.01_basic_task:broker
    Client:
        python examples/02_task_definition/01_basic_task.py

预期现象:
    - Worker 控制台显示三个任务的接收和执行日志
    - Client 显示三个任务的结果

生产提醒:
    - 显式指定 task_name 可避免重构时任务名变化导致的兼容性问题
    - 任务函数的参数必须可 JSON 序列化

技术要点:
    - 对比 Celery：无需 bind=True，用依赖注入替代 self
    - task_name 不指定时自动生成（模块路径:函数名）
    - 类型注解不影响运行时行为，但有助于 IDE 提示和文档生成
"""

from __future__ import annotations

import asyncio
import os

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend
from taskiq.serializers import JSONSerializer

QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:examples:02_task_definition:01_basic_task",
)

# ── 1. 创建 Broker + ResultBackend ──
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
).with_result_backend(
    RedisAsyncResultBackend(
        redis_url="redis://default:123456@localhost:6379/1",
        result_ex_time=3600,
        serializer=JSONSerializer()   # taskiq 默认使用的 PickleSerializer序列化，这在 redis 侧是人类不可读的，所以这里使用 JSONSerializer
    )
)

# ── 2. 任务定义：默认 task_name（自动生成） ──
# 自动生成的 task_name 格式: "模块路径:函数名"
# 例如: "examples.02_task_definition.01_basic_task:add"


# taskiq 与celery不同，celery task_name有一套完整自动拼接逻辑，而taskiq的自动拼接容易出错。
# TaskIQ 中 task_name 必须在当前 broker 的任务注册表中保持唯一，且 producer / worker 两侧必须完全一致。对于会被直接运行的教程文件，建议显式指定稳定的 task_name，避免脚本作为 __main__ 运行时，默认 task_name 推导受启动方式影响。
@broker.task(task_name="examples.02_task_definition.01_basic_task.add")
async def add(x: int, y: int) -> int:
    """两数相加（显式 task_name）。"""
    print(f"📦 [add] 收到: x={x}, y={y}")
    return x + y


# ── 3. 任务定义：显式指定 task_name ──
# 显式指定可避免重构（移动文件、重命名函数）时 task_name 变化
# 已入队的旧任务仍能被 Worker 正确路由


@broker.task(task_name="math:multiply")
async def multiply(x: int, y: int) -> int:
    """两数相乘（显式 task_name）。"""
    print(f"📦 [math:multiply] 收到: x={x}, y={y}")
    return x * y


# ── 4. 任务定义：完整类型注解 ──
# 类型注解不影响运行时，但有助于 IDE 提示和团队协作


@broker.task(task_name="user:build_greeting")
async def build_greeting(name: str, age: int, vip: bool = False) -> dict[str, str | int]:
    """构建用户问候信息（完整类型注解）。"""
    prefix = "尊敬的 VIP" if vip else "亲爱的"
    greeting = f"{prefix} {name}，欢迎回来！"
    print(f"📦 [build_greeting] 收到: name={name}, age={age}, vip={vip}")
    return {"greeting": greeting, "name": name, "age": age}


# ── 5. 客户端发送任务并获取结果 ──


async def main() -> None:
    """演示：发送三种任务定义模式的任务并获取结果。"""
    await broker.startup()
    try:
        print("🚀 发送三个任务...")
        print()

        # 任务 1：默认 task_name
        handle_add = await add.kiq(3, 7)
        result_add = await handle_add.wait_result(timeout=10)
        print(f"✅ add(3, 7)")
        print(f"   task_name    = {add.task_name}")
        print(f"   return_value = {result_add.return_value}")
        print()

        # 任务 2：显式 task_name
        handle_mul = await multiply.kiq(4, 5)
        result_mul = await handle_mul.wait_result(timeout=10)
        print(f"✅ multiply(4, 5)")
        print(f"   task_name    = {multiply.task_name}")
        print(f"   return_value = {result_mul.return_value}")
        print()

        # 任务 3：完整类型注解 + 关键字参数
        handle_greet = await build_greeting.kiq(name="小明", age=28, vip=True)
        result_greet = await handle_greet.wait_result(timeout=10)
        print(f"✅ build_greeting(name='小明', age=28, vip=True)")
        print(f"   task_name    = {build_greeting.task_name}")
        print(f"   return_value = {result_greet.return_value}")
        print()

        print("💡 对比 Celery:")
        print("   - Celery 需要 bind=True + self 参数访问任务上下文")
        print("   - TaskIQ 用依赖注入替代 self，更 Pythonic")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
