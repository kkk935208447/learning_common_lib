"""
目标: 用对比方式理解默认队列、自动路由与显式覆盖 (Queue Routing by Comparison)
关键概念:
  - 默认队列: 未命中规则的任务走 task_default_queue
  - 自动路由: task_routes 根据任务名把任务发到专用队列
  - 显式覆盖: apply_async(queue=...) 可以覆盖默认路由
关键 API: task_routes, task_queues, kombu.Queue, Exchange, apply_async(queue=...)
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/07_routing_and_queues
运行方式:
  Worker: celery -A examples.07_routing_and_queues.01_task_queues worker -l info -Q default,email_queue,report_queue,notification_queue
  Client: python examples/07_routing_and_queues/01_task_queues.py
预期现象:
  - default_task 走默认队列
  - send_email / generate_report / push_notification 自动路由到专用队列
  - apply_async(queue=...) 可以显式覆盖自动路由
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery
from kombu import Exchange, Queue

MODULE = "examples.07_routing_and_queues.01_task_queues"

app = Celery(
    MODULE,
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.task_default_queue = "default"

# Exchange 可以理解为“消息先投递到哪里再决定进哪个队列”。direct 类型表示：routing_key 精确匹配哪个队列绑定键，就把消息投到哪个队列。
default_exchange = Exchange("default", type="direct")

# task_queues 显式声明“系统里有哪些合法队列，以及它们和 exchange/routing_key 的绑定关系”。这在 RabbitMQ 一类 broker 中尤其直观；在 Redis broker 下也能帮助你把路由拓扑写清楚。这里 4 个队列都挂在同一个 direct exchange 上，只是绑定的 routing_key 不同。
app.conf.task_queues = (
    Queue("default", default_exchange, routing_key="default"),     # 没命中专用路由规则的任务，默认走这个队列。
    Queue("email_queue", default_exchange, routing_key="email"),   # send_email 命中 routing_key="email" 时进入 email_queue。
    Queue("report_queue", default_exchange, routing_key="report"),
    Queue("notification_queue", default_exchange, routing_key="notification"),
)

# task_routes 决定“某个任务名发布出去时默认带什么 queue/routing_key”。没有命中规则的任务，才回退到 app.conf.task_default_queue。
app.conf.task_routes = {
    f"{MODULE}.send_email": {"queue": "email_queue", "routing_key": "email"},  # "routing_key": "email" 与 上文的 routing_key="email" 要对应
    f"{MODULE}.generate_report": {"queue": "report_queue", "routing_key": "report"},
    f"{MODULE}.push_notification": {"queue": "notification_queue", "routing_key": "notification"},
}


def print_section(title: str) -> None:
    print(f"── {title} ──")


@app.task
def send_email(to: str, subject: str) -> dict[str, str]:
    print(f"  📧 发送邮件: to={to}, subject={subject}")
    return {"task": "send_email", "status": "sent", "to": to}


@app.task
def generate_report(report_type: str, year: int) -> dict[str, str]:
    print(f"  📊 生成报表: type={report_type}, year={year}")
    return {"task": "generate_report", "status": "generated", "type": report_type}


@app.task
def push_notification(user_id: int, message: str) -> dict[str, str]:
    print(f"  🔔 推送通知: user_id={user_id}, message={message}")
    return {"task": "push_notification", "status": "pushed", "user_id": str(user_id)}


@app.task
def default_task(data: str) -> dict[str, str]:
    print(f"  ⚙️ 默认任务: data={data}")
    return {"task": "default_task", "status": "done", "data": data}


async def wait_result(label: str, async_result: Any) -> Any:
    payload = await asyncio.to_thread(async_result.get, timeout=30)
    print(f"  ✅ {label}: {payload}")
    return payload


async def main() -> None:
    print("🚀 Celery 队列路由对比示例\n")

    print_section("场景 A: 没有命中路由规则时，任务走 default 队列")
    default_result = await asyncio.to_thread(default_task.delay, "普通数据处理")
    await wait_result("default_task -> default", default_result)
    print("  结论: default_task 没有出现在 task_routes 里，所以它会走 task_default_queue。\n")

    print_section("场景 B: 命中 task_routes 时，任务自动路由到专用队列")
    print("  当前自动路由表:")
    for task_name, route in app.conf.task_routes.items():
        print(f"    {task_name} -> queue={route['queue']}, routing_key={route.get('routing_key', 'N/A')}")
    print()

    email_result = await asyncio.to_thread(send_email.delay, "user@example.com", "欢迎注册")
    report_result = await asyncio.to_thread(generate_report.delay, "monthly_sales", 2025)
    notify_result = await asyncio.to_thread(push_notification.delay, 1001, "您有新消息")

    await wait_result("send_email -> email_queue", email_result)
    await wait_result("generate_report -> report_queue", report_result)
    await wait_result("push_notification -> notification_queue", notify_result)
    print("  结论: task_routes 负责把不同任务自动分流到不同队列。\n")

    print_section("场景 C: apply_async(queue=...) 可以显式覆盖默认路由")
    override_result = await asyncio.to_thread(
        send_email.apply_async,
        args=("override@example.com", "强制改走 default"),
        queue="default",
    )
    await wait_result("send_email apply_async(queue='default')", override_result)
    print("  结论: 自动路由是默认策略，但发布侧仍可以显式指定 queue 覆盖它。\n")

    print_section("场景 D: 逻辑分流 vs 部署分流")
    lines = [
        "单 worker 消费所有队列: celery -A examples.07_routing_and_queues.01_task_queues worker -l info -Q default,email_queue,report_queue,notification_queue",
        "独立邮件 worker:         celery -A myproj.celery_app:app worker -Q email_queue",
        "独立报表 worker:         celery -A myproj.celery_app:app worker -Q report_queue",
        "默认 + 邮件混合 worker:  celery -A myproj.celery_app:app worker -Q default,email_queue",
    ]
    for line in lines:
        print(f"  {line}")
    print()
    print("  结论: task_routes 解决的是逻辑分流；独立 worker 部署解决的是资源隔离和扩缩容。")


if __name__ == "__main__":
    asyncio.run(main())
