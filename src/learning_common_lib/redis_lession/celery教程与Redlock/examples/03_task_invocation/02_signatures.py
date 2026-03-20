"""
目标: 演示 Celery Signature、偏函数、不可变签名、克隆与修改
关键 API: signature(), s(), si(), .delay(), .apply_async(), .clone()
Python 版本: 3.11+
运行方式 (两个终端):
  终端1 (worker):  cd src/learning_common_lib/redis_lession/celery教程与Redlock && uv run celery -A examples.03_task_invocation.02_signatures worker --loglevel=info -Q default,math_queue
  终端2 (client):  cd src/learning_common_lib/redis_lession/celery教程与Redlock && uv run python examples/03_task_invocation/02_signatures.py
预期现象: 展示签名的创建、调用、偏函数绑定、不可变签名及克隆
生产提醒: 签名是 workflow (chain/group/chord) 的基础，务必理解 immutable 的含义
注意: 手动运行多个示例前建议清理 Redis: redis-cli -a 123456 -n 0 FLUSHDB 或者运行 src/learning_common_lib/redis_lession/celery教程与Redlock/examples/清理redis的代码.py 
"""

from __future__ import annotations

import asyncio

from celery import Celery

# ── 1. 创建应用 ──
app = Celery(
    "examples.03_task_invocation.02_signatures",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
# 默认队列名一般是 celery（除非你在配置里改过），这里改为 defult
app.conf.task_default_queue = "default"


@app.task
def add(x: int, y: int) -> int:
    print(f"  📦 add({x}, {y}) = {x + y}")
    return x + y


@app.task
def mul(x: int, y: int) -> int:
    print(f"  📦 mul({x}, {y}) = {x * y}")
    return x * y


# ── 2. 入口 ──
async def main() -> None:
    print("🚀 Signatures 与偏函数示例\n")

    # ── signature() 创建 ──
    print("── signature() 创建签名 ──")
    # 使用任务的 .name 属性获取注册名
    sig1 = add.signature(args=(2, 3))
    print(f"  签名对象: {sig1!r}")
    print(f"  类型: {type(sig1).__name__}")
    print(f"  💡 也可以用字符串: signature('{add.name}', args=(2, 3), app=app)")
    r1 = await asyncio.to_thread(sig1.delay)
    print(f"  ✅ 结果: {await asyncio.to_thread(r1.get, timeout=30)}\n")

    # ── s() 快捷方式 ──
    print("── s() 快捷方式 ──")
    sig2 = add.s(10, 20)
    print(f"  签名对象: {sig2!r}")
    r2 = await asyncio.to_thread(sig2.delay)
    print(f"  ✅ 结果: {await asyncio.to_thread(r2.get, timeout=30)}\n")

    # ── 偏函数 (Partial) ──
    print("── 偏函数: s() 只绑定部分参数 ──")
    # 只绑定第一个参数，第二个参数稍后提供
    partial_add = add.s(10)  # x=10, y 待定
    print(f"  偏函数签名: {partial_add!r}")
    # 调用时补充剩余参数
    r3 = await asyncio.to_thread(partial_add.delay, 5)  # y=5
    print(f"  ✅ add(10, 5) = {await asyncio.to_thread(r3.get, timeout=30)}")
    print(f"  💡 偏函数在 chain 中很有用: 前一个任务的结果作为第一个参数传入\n")

    # ── 不可变签名 si() ──
    print("── si() 不可变签名 ──")
    immutable_sig = add.si(100, 200)
    print(f"  不可变签名: {immutable_sig!r}")
    print(f"  immutable: {immutable_sig.immutable}")
    # 不可变签名忽略额外传入的参数
    r4 = await asyncio.to_thread(immutable_sig.delay)
    print(f"  ✅ 结果: {await asyncio.to_thread(r4.get, timeout=30)}")
    print(f"  💡 si() 在 chain 中忽略前一个任务的返回值，始终用预设参数\n")

    # ── 调用签名的三种方式 ──
    print("── 调用签名的三种方式 ──")
    sig3 = mul.s(6, 7)

    # 方式一: delay()
    r5 = await asyncio.to_thread(sig3.delay)
    print(f"  ✅ sig.delay() = {await asyncio.to_thread(r5.get, timeout=30)}")

    # 方式二: apply_async()
    r6 = await asyncio.to_thread(sig3.apply_async)
    print(f"  ✅ sig.apply_async() = {await asyncio.to_thread(r6.get, timeout=30)}")

    # 方式三: 直接调用 (同步，不经过 broker，返回原始值)
    r7 = sig3()
    print(f"  ✅ sig() 直接调用 = {r7}\n")

    # ── clone() 克隆与修改 ──
    print("── clone() 克隆与修改 ──")
    original = add.s(1, 2)
    print(f"  原始签名: {original!r}")

    # 克隆后通过 set() 修改选项（clone 不替换 args，而是追加）
    cloned = original.clone()
    cloned.args = (10, 20)  # 直接替换参数
    print(f"  克隆签名: {cloned!r}")

    r8 = await asyncio.to_thread(original.delay)
    r9 = await asyncio.to_thread(cloned.delay)
    print(f"  ✅ 原始结果: {await asyncio.to_thread(r8.get, timeout=30)}")
    print(f"  ✅ 克隆结果: {await asyncio.to_thread(r9.get, timeout=30)}")
    print(f"  💡 clone() 创建独立副本，修改不影响原始签名\n")

    # ── 签名设置选项 ──
    print("── 签名附加选项 ──")
    sig_with_opts = add.s(5, 5).set(
        queue="math_queue",
        countdown=0,
        expires=300,
    )
    print(f"  带选项的签名: {sig_with_opts!r}")
    print(f"  options: {sig_with_opts.options}")
    r10 = await asyncio.to_thread(sig_with_opts.delay)
    print(f"  ✅ 结果: {await asyncio.to_thread(r10.get, timeout=30)}\n")

    print("💡 signature/s() 是 Celery workflow 的基石")
    print("💡 偏函数让 chain 中的任务可以接收前一步的结果")
    print("💡 si() 不可变签名用于 chain 中不需要前一步结果的场景")


if __name__ == "__main__":
    asyncio.run(main())
