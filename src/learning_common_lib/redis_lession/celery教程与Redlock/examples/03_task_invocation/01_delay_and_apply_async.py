"""
目标: 对比 delay() 与 apply_async() 的能力边界 (delay vs apply_async)
关键概念:
  - delay(): 语法糖，适合最简单的 args/kwargs 调用
  - apply_async(): 完整接口，支持 countdown/eta/expires/queue
  - 对比式理解: 先看 delay 够不够，再看为什么要切换到 apply_async
关键 API: task.delay(), task.apply_async(), countdown, eta, expires, queue
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/03_task_invocation
运行方式:
  Worker: celery -A examples.03_task_invocation.01_delay_and_apply_async worker -l info -Q default,high_priority,greetings
  Client: python examples/03_task_invocation/01_delay_and_apply_async.py

开启 default, high_priority, greetings 队列后的redis 0 数据库的 key 如下：
    Key (键名)	Type (类型)	Value (值 / 集合内容)
    _kombu.bi...	set	[celerycelery]                        # 默认队列
    _kombu.bi...	set	[defaultdefault]                      # 开启 default 队列
    _kombu.bi...	set	[greetingsgreetings]                  # 开启 greetings 队列
    _kombu.bi...	set	[high_priorityhigh_priority]          # 开启 high_priority 队列

预期现象:
  - delay() 与 apply_async(args=..., kwargs=...) 在基础调用上效果一致
  - 一旦需要调度或路由，必须切到 apply_async()
  - queue/countdown/eta/expires 等能力构成了 apply_async 的完整价值
注意: 手动运行多个示例前建议清理 Redis: redis-cli -a 123456 -n 0 FLUSHDB 或者运行 src/learning_common_lib/redis_lession/celery教程与Redlock/examples/清理redis的代码.py 
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from celery import Celery

MODULE = "examples.03_task_invocation.01_delay_and_apply_async"

app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
# 设置默认的celery的默认队列为 default，注意默认的 celery 的队列不是default
app.conf.task_default_queue = "default"


def print_section(title: str) -> None:
    print(f"── {title} ──")


# 通常来说，当task 未给定 name 参数时，celery 会从自动拼接： worker启动模块路径 + 函数名进行自动拼接为： ”模块路径.func“。因此如果是这种方式需要满足： ”Celery 实例名 == Wroker 启动模块路径“。
# 而如果task 给定 name 参数时，需要该字符串在整个celery都是独一无二的（celery是根据这个字符串来判断谁提交的任务），这时 celery 实例名和 task name 可以随意命名。
# 如：@app.task(name="ddjdddddddjdjdj")
# 强烈建议使用显示注册：“模块路径.func” 来命名，如：@app.task(name="examples.03_task_invocation.01_delay_and_apply_async.add")
@app.task(bind=True)
def add(self: Any, x: int, y: int) -> int:
    print(f"  📦 [{self.request.id}] add({x}, {y}) -> {x + y}")
    return x + y


@app.task(bind=True)
def greet(self: Any, name: str, greeting: str = "你好") -> str:
    msg = f"{greeting}, {name}!"
    print(f"  📦 [{self.request.id}] {msg}")
    return msg


async def wait_result(label: str, async_result: Any) -> Any:
    payload = await asyncio.to_thread(async_result.get, timeout=30)
    print(f"  ✅ {label}: {payload}")
    return payload


async def main() -> None:
    print("🚀 delay() vs apply_async() 对比示例\n")

    print_section("场景 A: delay() 适合最简单的调用")
    delay_add = await asyncio.to_thread(add.delay, 3, 5)
    await wait_result("delay add", delay_add)

    delay_greet = await asyncio.to_thread(greet.delay, "Alice", greeting="Hello")
    await wait_result("delay greet", delay_greet)
    print("  结论: 如果你只需要传 args/kwargs，delay() 最短、最直观。\n")

    print_section("场景 B: apply_async() 先从“等价写法”开始")
    apply_add = await asyncio.to_thread(add.apply_async, args=(3, 5))
    await wait_result("apply_async add", apply_add)

    apply_greet = await asyncio.to_thread(
        greet.apply_async,
        args=("Alice",),
        kwargs={"greeting": "Hello"},
    )
    await wait_result("apply_async greet", apply_greet)
    print("  结论: 在基础调用层面，delay() 只是 apply_async(args=..., kwargs=...) 的语法糖。\n")

    print_section("场景 C: 一旦需要调度能力，delay() 就不够了")
    countdown_result = await asyncio.to_thread(add.apply_async, args=(100, 200), countdown=2)
    await wait_result("countdown=2", countdown_result)

    eta_time = datetime.now(tz=timezone.utc) + timedelta(seconds=3)
    eta_result = await asyncio.to_thread(add.apply_async, args=(10, 20), eta=eta_time)
    await wait_result("eta=future_time", eta_result)

    expires_result = await asyncio.to_thread(
        add.apply_async,
        args=(6, 6),
        expires=datetime.now(tz=timezone.utc) + timedelta(minutes=5),
    )
    await wait_result("expires=datetime", expires_result)
    print("  结论: countdown / eta / expires 都属于 apply_async 的专属能力。\n")

    print_section("场景 D: 一旦需要路由能力，也必须切到 apply_async()")
    route_result = await asyncio.to_thread(
        greet.apply_async,
        args=("Bob",),
        kwargs={"greeting": "Hi"},
        countdown=1,
        queue="greetings",
        expires=120,
    )
    await wait_result("queue=greetings + countdown + expires", route_result)
    print("  结论: queue 这样的发布侧路由控制，也只能通过 apply_async() 表达。\n")

    print_section("最终判断")
    summary_rows = [
        ("delay()", "最短语法", "仅适合 args/kwargs"),
        ("apply_async()", "完整接口", "调度、过期、路由、优先级都靠它"),
        ("迁移策略", "先会用 delay", "但生产发布侧应优先掌握 apply_async"),
    ]
    for label, value, note in summary_rows:
        print(f"  {label:<15} {value:<12} {note}")


if __name__ == "__main__":
    asyncio.run(main())
