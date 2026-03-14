"""
目标: 演示任务装饰器参数与任务上下文访问 (Task Decorator Parameters & Context Access)
关键概念:
  - bind=True 将任务实例绑定到第一个参数，提供任务上下文访问能力
  - 任务继承机制：自定义 Task 基类扩展任务行为
  - self.request 属性：任务运行时元数据（ID、重试次数、路由信息等）
关键 API: @app.task(bind=True), self.request, Task 基类, ignore_result
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/02_task_definition
运行方式:
  Worker: celery -A examples.02_task_definition.01_basic_task worker -l info
    (bind=True 的任务会在日志中显示详细的 request 信息)
  Client: python examples/02_task_definition/01_basic_task.py
    (调用各种类型的任务并观察其行为差异)
预期现象:
  - bind=True 任务打印任务 ID、重试次数、delivery_info 等上下文信息
  - ignore_result=True 任务不在 backend 存储结果，节省内存
  - 自定义 Task 基类的钩子方法被正确调用
生产提醒:
  - bind=True 任务的第一个参数是 self，调用时不要传递 self 参数
  - ignore_result=True 适用于通知类任务，可显著减少 Redis 内存占用
技术要点:
  - self.request.id 是任务的唯一标识符，用于结果存储和状态跟踪
  - delivery_info 包含队列、交换机、路由键等消息传递信息
  - 任务继承允许在 on_success、on_failure 等钩子中添加通用逻辑
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery, Task

# ── 1. 创建应用 ──
app = Celery(
    "examples.02_task_definition.01_basic_task",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)


# ── 2. bind=True — 访问 self.request ──
@app.task(bind=True)
def inspect_request(self: Task, msg: str) -> dict[str, Any]:
    """bind=True 让任务第一个参数为 self，可访问 request 上下文"""
    req = self.request
    info = {
        "task_id": req.id,
        "task_name": self.name,
        "retries": req.retries,
        "delivery_info": req.delivery_info,
        "hostname": req.hostname,
        "args": req.args,
        "kwargs": req.kwargs,
    }
    print(f"  📦 request 属性:")
    for k, v in info.items():
        print(f"     {k}: {v}")
    return info


# ── 3. name 参数 — 自定义任务名 ──
@app.task(name="math.multiply")
def multiply(x: int, y: int) -> int:
    """自定义任务名，覆盖默认的 module.function 命名"""
    print(f"  📦 自定义任务名执行: {x} * {y} = {x * y}")
    return x * y


# ── 4. ignore_result — 不存储结果 ──
@app.task(ignore_result=True)
def fire_and_forget(msg: str) -> None:
    """ignore_result=True: 不存储返回值到 backend，节省资源"""
    print(f"  📦 fire_and_forget: {msg}")


# ── 5. 任务继承 — 自定义 Task 基类 ──
class LoggingTask(Task):
    """自定义基类，为所有任务添加生命周期钩子"""

    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        print(f"  🎉 [LoggingTask] 任务成功: {self.name} -> {retval}")

    def on_failure(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        print(f"  ❌ [LoggingTask] 任务失败: {self.name} -> {exc}")

    def before_start(self, task_id: str, args: tuple, kwargs: dict) -> None:
        print(f"  ⏳ [LoggingTask] 任务开始: {self.name}")


@app.task(base=LoggingTask, bind=True)
def divide(self: Task, x: int, y: int) -> float:
    """使用自定义基类的任务"""
    result = x / y
    print(f"  📦 {x} / {y} = {result}")
    return result


# ── 6. 入口 ──
async def main() -> None:
    print("🚀 @app.task 参数与任务继承示例\n")

    # bind=True 演示
    print("── bind=True: 访问 self.request ──")
    r1 = await asyncio.to_thread(inspect_request.delay, "hello celery")
    print(f"  ✅ 返回: task_id={(await asyncio.to_thread(r1.get, timeout=30))['task_id']}\n")

    # name 参数演示
    print("── name 参数: 自定义任务名 ──")
    r2 = await asyncio.to_thread(multiply.delay, 6, 7)
    print(f"  ✅ 任务注册名: {multiply.name}")
    print(f"  ✅ 结果: {await asyncio.to_thread(r2.get, timeout=30)}\n")

    # ignore_result 演示
    print("── ignore_result: 不存储结果 ──")
    r3 = await asyncio.to_thread(fire_and_forget.delay, "这条消息不保存结果")
    print(f"  ✅ result.ready(): {await asyncio.to_thread(r3.ready)}")
    print(f"  ✅ ignore_result=True 时结果不存储到 backend\n")

    # 任务继承演示
    print("── Task 基类继承: 生命周期钩子 ──")
    r4 = await asyncio.to_thread(divide.delay, 10, 3)
    print(f"  ✅ 结果: {(await asyncio.to_thread(r4.get, timeout=30)):.4f}\n")

    print("💡 bind=True 是生产中最常用的模式，可访问 task_id、重试次数等上下文")
    print("💡 自定义 Task 基类适合统一日志、监控、错误处理等横切关注点")


if __name__ == "__main__":
    asyncio.run(main())
