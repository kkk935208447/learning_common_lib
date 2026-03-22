"""
目标: 通过真实任务调用讲清 task_acks_late 与 broker_transport_options 的职责边界
关键概念:
  - task_acks_late: 任务确认时机，属于消费语义
  - broker_transport_options: broker 传输层配置，属于消息通道行为
  - 二者经常一起出现，但解决的是不同层级的问题
关键 API: task_acks_late, task_reject_on_worker_lost, broker_transport_options, .apply_async, .get, .state, .ready, .forget
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/01_app_and_config
运行方式:
  在 Celery 中，solo 模式是一种特殊的执行池（Execution Pool）类型。与默认的 prefork（多进程）模式不同，它在一个单线程的进程中顺序执行任务
  Worker: celery -A examples.01_app_and_config.03_acks_late_vs_broker_transport worker -l info -P solo
  Client: python examples/01_app_and_config/03_acks_late_vs_broker_transport.py
预期现象:
  - 客户端打印 acks_late 与 broker_transport_options 配置
  - Worker 执行任务时也会打印同样的配置和 request 信息
  - 客户端轮询任务状态并拿到最终结果
生产提醒:
  - acks_late 解决不了幂等性问题；任务仍然需要设计成可重复执行
  - transport_options 也不等于可靠消费，它只是 broker 这一层的补充配置
注意: 手动运行多个示例前建议清理 Redis: redis-cli -a 123456 -n 0 FLUSHDB 或者运行 src/learning_common_lib/redis_lession/celery教程与Redlock/examples/清理redis的代码.py
**推荐：**你使用 purge -f 命令清理队伍里的任务，避免对后面启动的 Worker 的任务进行污染。命令为：uv run celery -A examples.01_app_and_config.03_acks_late_vs_broker_transport purge -f
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from celery import Celery, Task


def build_app() -> Celery:
    app = Celery(
        "acks_late_vs_broker_transport",
        broker="redis://:123456@localhost:6379/0",
        backend="redis://:123456@localhost:6379/1",
    )
    app.conf.update(
        task_acks_late=True,  # 开启“延迟确认(ack late)”: worker 只有在任务成功执行结束后才向 broker 发送 ack；worker 在执行中途崩溃/被杀时，消息会保持未确认从而可能被重新投递（至少一次语义）。
        task_reject_on_worker_lost=True,  # worker 异常丢失时将任务标记为 reject，让 broker 触发重新投递；通常与 acks_late 组合使用以避免“worker 死了但消息已 ack 导致任务丢失”
        task_track_started=True,  # 让任务进入执行时上报 STARTED 状态（便于观测/监控）；与确认时机无关，只影响状态追踪
        broker_transport_options={  # broker 传输层/驱动层的额外参数（这里针对 Redis transport），用于控制“消息在 broker 侧”的一些行为，不改变任务函数本身逻辑
            "visibility_timeout": 1800,  # Redis 作为 broker 时：未 ack 的消息在该秒数内对其他 worker 不可见；超时后会被视为“可重新投递”（需要与你的最长任务耗时匹配，避免任务仍在跑却被重复投递）
        },
    )
    return app


app = build_app()


# 通常来说，当task 未给定 name 参数时，celery 会从自动拼接： worker启动模块路径 + 函数名进行自动拼接为： ”模块路径.func“。因此如果是这种方式需要满足： ”Celery 实例名 == Wroker 启动模块路径“。
# 而如果task 给定 name 参数时，需要该字符串在整个celery都是独一无二的（celery是根据这个字符串来判断谁提交的任务），这时 celery 实例名和 task name 可以随意命名。
# 如：@app.task(name="ddjdddddddjdjdj")
# 强烈建议使用显示注册：“模块路径.func” 来命名，如：@app.task(name="examples.01_app_and_config.03_acks_late_vs_broker_transport.inspect_runtime")
@app.task(bind=True, name="examples.acks_late.inspect_runtime")
def inspect_runtime(self: Task, job_name: str, sleep_seconds: int = 2) -> dict[str, Any]:
    """打印 worker 侧配置与 request 信息。"""
    print(f"  📦 开始执行任务: {job_name}")
    print("  acks_late 全局配置:", self.app.conf.task_acks_late)
    print("  broker_transport_options:", self.app.conf.broker_transport_options)
    print("  request.id:", self.request.id)
    print("  request.retries:", self.request.retries)
    print("  request.delivery_info:", self.request.delivery_info)
    time.sleep(sleep_seconds)
    return {
        "job_name": job_name,
        "acks_late": self.app.conf.task_acks_late,
        "visibility_timeout": self.app.conf.broker_transport_options.get("visibility_timeout"),
        "message": "任务执行完成；这里观察到的是运行时配置，而不是静态概念",
    }


async def main() -> None:
    print("🚀 acks_late 与 broker_transport_options 差异示例\n")
    print("── 当前配置 ──")
    print("acks_late 全局配置:", app.conf.task_acks_late)
    print("broker_transport_options:", app.conf.broker_transport_options)
    print()

    print("── 提交任务 ──")
    result = await asyncio.to_thread(
        inspect_runtime.apply_async,
        args=("ack-demo",),
        kwargs={"sleep_seconds": 2},
    )
    print("  task_id:", result.id)
    print("  初始状态:", await asyncio.to_thread(lambda: result.state))
    print()

    print("── 轮询状态 ──: PENDING -> STARTED -> SUCCESS")
    for _ in range(10):
        state = await asyncio.to_thread(lambda: result.state)
        print("  当前状态:", state)
        if await asyncio.to_thread(result.ready):
            break
        await asyncio.sleep(0.5)
    print()

    print("── 获取结果 ──")
    value = await asyncio.to_thread(result.get, timeout=20)
    print("  结果:", value)
    # .forget：你已经拿到结果并处理完了，不想在 Redis/DB 等后端里继续保留这条结果记录。
    await asyncio.to_thread(result.forget)
    print()

    print("── 运行时如何理解这两个配置 ──")
    print("1. task_acks_late 决定 worker 在任务执行前还是执行后 ack。")
    print("2. broker_transport_options 影响 broker 如何管理未确认消息。")
    print("3. 本示例里你能看到它们都进入了运行时，但作用层次不同。")
    print("4. acks_late 是消费语义；visibility_timeout 是 broker 侧补充配置。")


if __name__ == "__main__":
    asyncio.run(main())
