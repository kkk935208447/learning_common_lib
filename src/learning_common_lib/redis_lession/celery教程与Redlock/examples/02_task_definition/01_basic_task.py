"""
目标: 演示 @app.task 参数: bind, name, ignore_result, 任务继承, self.request 属性
关键 API: @app.task(bind=True), self.request, Task 基类
Python 版本: 3.11+
运行方式 (两个终端):
  终端1 (worker):  cd src/learning_common_lib/redis_lession/celery教程与Redlock && uv run celery -A examples.02_task_definition.01_basic_task worker --loglevel=info
  终端2 (client):  cd src/learning_common_lib/redis_lession/celery教程与Redlock && uv run python examples/02_task_definition/01_basic_task.py
预期现象: 打印任务 ID、重试次数、delivery_info 等 request 属性
生产提醒: bind=True 的任务第一个参数是 self，签名与普通函数不同，调用时勿传 self
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
    print(f"  ✅ result.ready(): {r3.ready()}")
    print(f"  ✅ ignore_result=True 时结果不存储到 backend\n")

    # 任务继承演示
    print("── Task 基类继承: 生命周期钩子 ──")
    r4 = await asyncio.to_thread(divide.delay, 10, 3)
    print(f"  ✅ 结果: {(await asyncio.to_thread(r4.get, timeout=30)):.4f}\n")

    print("💡 bind=True 是生产中最常用的模式，可访问 task_id、重试次数等上下文")
    print("💡 自定义 Task 基类适合统一日志、监控、错误处理等横切关注点")


if __name__ == "__main__":
    asyncio.run(main())
