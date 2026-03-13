"""
目标: 演示 delay() 与 apply_async() 的区别及 apply_async 参数
关键 API: task.delay(), task.apply_async(), countdown, eta, expires, queue
Python 版本: 3.11+
运行方式 (两个终端):
  终端1 (worker):  cd src/learning_common_lib/redis_lession/celery教程与Redlock && uv run celery -A examples.03_task_invocation.01_delay_and_apply_async worker --loglevel=info -Q default,high_priority,greetings
  终端2 (client):  cd src/learning_common_lib/redis_lession/celery教程与Redlock && uv run python examples/03_task_invocation/01_delay_and_apply_async.py
预期现象: 展示两种调用方式及 apply_async 的各种参数效果 (countdown 会真正延迟，eta 会真正调度)
生产提醒: countdown/eta 依赖 worker 时钟，跨时区部署时注意使用 UTC
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from celery import Celery

# ── 1. 创建应用 ──
app = Celery(
    "examples.03_task_invocation.01_delay_and_apply_async",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)


# ── 2. 示例任务 ──
@app.task(bind=True)
def add(self, x: int, y: int) -> int:
    print(f"  📦 [{self.request.id}] {x} + {y} = {x + y}")
    return x + y


@app.task(bind=True)
def greet(self, name: str, greeting: str = "你好") -> str:
    msg = f"{greeting}, {name}!"
    print(f"  📦 [{self.request.id}] {msg}")
    return msg


# ── 3. 入口 ──
async def main() -> None:
    print("🚀 delay() vs apply_async() 示例\n")

    # ── delay(): 快捷方式，只接受位置参数和关键字参数 ──
    print("── delay() 快捷调用 ──")
    r1 = await asyncio.to_thread(add.delay, 3, 5)
    print(f"  ✅ 结果: {await asyncio.to_thread(r1.get, timeout=30)}")
    print(f"  💡 delay(3, 5) 等价于 apply_async(args=(3, 5))\n")

    # delay 也支持关键字参数
    r2 = await asyncio.to_thread(greet.delay, "Alice", greeting="Hello")
    print(f"  ✅ 结果: {await asyncio.to_thread(r2.get, timeout=30)}\n")

    # ── apply_async(): 完整控制 ──
    print("── apply_async() 完整控制 ──")

    # 基本调用
    print("  🔸 基本调用:")
    r3 = await asyncio.to_thread(
        add.apply_async,
        args=(10, 20),
    )
    print(f"  ✅ 结果: {await asyncio.to_thread(r3.get, timeout=30)}\n")

    # countdown: 延迟 N 秒后执行
    print("  🔸 countdown=2 (延迟2秒后 worker 才执行):")
    r4 = await asyncio.to_thread(
        add.apply_async,
        args=(100, 200),
        countdown=2,
    )
    print(f"  ✅ 结果: {await asyncio.to_thread(r4.get, timeout=30)}")
    print(f"  💡 countdown=2: worker 收到任务后等待2秒再执行\n")

    # eta: 指定执行时间
    print("  🔸 eta (指定未来时间执行):")
    future_time = datetime.now(tz=timezone.utc) + timedelta(seconds=3)
    r5 = await asyncio.to_thread(
        add.apply_async,
        args=(1000, 2000),
        eta=future_time,
    )
    print(f"  ✅ 结果: {await asyncio.to_thread(r5.get, timeout=30)}")
    print(f"  💡 eta={future_time.isoformat()}, worker 会等到指定时间才执行\n")

    # expires: 过期时间（超时未执行则丢弃）
    print("  🔸 expires (任务过期时间):")
    r6 = await asyncio.to_thread(
        add.apply_async,
        args=(5, 5),
        expires=60,  # 60秒后过期
    )
    print(f"  ✅ 结果: {await asyncio.to_thread(r6.get, timeout=30)}")
    print(f"  💡 expires=60: 如果60秒内未被 worker 取走则丢弃\n")

    # 也可以用 datetime 指定过期时间
    r7 = await asyncio.to_thread(
        add.apply_async,
        args=(6, 6),
        expires=datetime.now(tz=timezone.utc) + timedelta(minutes=5),
    )
    print(f"  ✅ expires 也支持 datetime: {await asyncio.to_thread(r7.get, timeout=30)}\n")

    # queue: 指定队列
    print("  🔸 queue (指定目标队列):")
    r8 = await asyncio.to_thread(
        add.apply_async,
        args=(7, 8),
        queue="high_priority",
    )
    print(f"  ✅ 结果: {await asyncio.to_thread(r8.get, timeout=30)}")
    print(f"  💡 生产中可用 queue 实现优先级路由\n")

    # 组合使用
    print("── 组合使用多个参数 ──")
    r9 = await asyncio.to_thread(
        greet.apply_async,
        args=("Bob",),
        kwargs={"greeting": "Hi"},
        countdown=3,
        expires=120,
        queue="greetings",
    )
    print(f"  ✅ 结果: {await asyncio.to_thread(r9.get, timeout=30)}\n")

    print("💡 delay() 是 apply_async() 的语法糖，只能传 args/kwargs")
    print("💡 需要 countdown/eta/expires/queue 等控制时，必须用 apply_async()")


if __name__ == "__main__":
    asyncio.run(main())
