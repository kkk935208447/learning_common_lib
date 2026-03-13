"""
目标: 演示多队列路由配置与任务分发策略 (Multi-Queue Routing & Task Distribution Strategies)
关键概念:
  - 队列路由机制：通过 task_routes 将不同类型任务分发到专用队列
  - 队列隔离策略：email、report、notification 队列独立处理，避免相互影响
  - Worker 队列绑定：-Q 参数控制 worker 监听的队列范围
关键 API: task_routes, task_queues, kombu.Queue, Exchange, -Q 参数
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/06_routing_and_queues
运行方式:
  Worker: celery -A examples.06_routing_and_queues.01_task_queues worker -l info -Q default,email_queue,report_queue,notification_queue
    (启动 worker 监听所有队列，观察任务路由)
  Client: python examples/06_routing_and_queues/01_task_queues.py
    (发送不同类型任务到各自队列)
预期现象:
  - 不同任务函数被自动路由到对应队列
  - Worker 日志显示从不同队列消费任务
  - Redis 中可观察到各队列的任务分布
生产提醒:
  - 生产环境建议为每个队列启动独立 worker 进程，实现资源隔离
  - 高优先级队列可配置更多 worker 实例
技术要点:
  - Exchange 和 routing_key 是 AMQP 概念，Redis broker 会忽略它们
  - task_routes 支持函数名匹配和正则表达式匹配
  - 队列分离有助于监控、扩缩容和故障隔离
"""

from __future__ import annotations

import asyncio

from celery import Celery
from kombu import Exchange, Queue

# ── 1. 创建 Celery 应用并配置队列 ──
app = Celery(
    "examples.06_routing_and_queues.01_task_queues",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
# 默认队列名一般是 celery（除非你在配置里改过），这里改为 defult
app.conf.task_default_queue = "default"

# ── 2. 定义交换机和队列 ──
# ⚠️ Exchange 和 routing_key 是 AMQP (RabbitMQ) 概念。Redis broker 会忽略它们，只看 Queue 名称。
# 这里写出来是为了展示完整的 AMQP 配置语法，方便迁移到 RabbitMQ。如果只用 Redis，可以简化为 Queue("email_queue") 即可。
default_exchange = Exchange("default", type="direct")

app.conf.task_queues = (
    Queue("default", default_exchange, routing_key="default"),
    Queue("email_queue", default_exchange, routing_key="email"),
    Queue("report_queue", default_exchange, routing_key="report"),
    Queue("notification_queue", default_exchange, routing_key="notification"),
)

# ── 3. 配置路由规则 ──
# 方式一：字典映射 — 任务名 → 队列
app.conf.task_routes = {
    "examples.06_routing_and_queues.01_task_queues.send_email": {"queue": "email_queue", "routing_key": "email"},
    "examples.06_routing_and_queues.01_task_queues.generate_report": {"queue": "report_queue", "routing_key": "report"},
    "examples.06_routing_and_queues.01_task_queues.push_notification": {"queue": "notification_queue", "routing_key": "notification"},
    # 未匹配的任务走 default 队列
}

# 方式二（注释说明）：也可以用函数路由
# def route_task(name, args, kwargs, options, task=None, **kw):
#     if "email" in name:
#         return {"queue": "email_queue"}
#     return {"queue": "default"}
# app.conf.task_routes = (route_task,)


# ── 4. 定义不同类型的任务 ──
@app.task
def send_email(to: str, subject: str) -> dict[str, str]:
    """邮件发送任务 → 路由到 email_queue"""
    print(f"  📧 发送邮件: to={to}, subject={subject}")
    return {"status": "sent", "to": to}


@app.task
def generate_report(report_type: str, year: int) -> dict[str, str]:
    """报表生成任务 → 路由到 report_queue"""
    print(f"  📊 生成报表: type={report_type}, year={year}")
    return {"status": "generated", "type": report_type}


@app.task
def push_notification(user_id: int, message: str) -> dict[str, str]:
    """推送通知任务 → 路由到 notification_queue"""
    print(f"  🔔 推送通知: user_id={user_id}, message={message}")
    return {"status": "pushed", "user_id": user_id}


@app.task
def default_task(data: str) -> dict[str, str]:
    """默认任务 → 走 default 队列"""
    print(f"  ⚙️ 默认任务: data={data}")
    return {"status": "done", "data": data}


# ── 5. 入口 ──
async def main() -> None:
    print("🚀 Celery 多队列路由示例\n")

    # 打印路由表
    print("── 路由配置表 ──")
    for task_name, route in app.conf.task_routes.items():
        print(f"  📋 {task_name} → queue={route['queue']}, key={route.get('routing_key', 'N/A')}")
    print()

    # 打印队列配置
    print("── 队列配置 ──")
    for q in app.conf.task_queues:
        print(f"  📦 队列: {q.name}, 交换机: {q.exchange.name}, routing_key: {q.routing_key}")
    print()

    # 调度任务到不同队列
    print("── 调度任务 ──")

    r1 = await asyncio.to_thread(send_email.delay, "user@example.com", "欢迎注册")
    print(f"  ✅ send_email 结果: {await asyncio.to_thread(r1.get, timeout=30)}\n")

    r2 = await asyncio.to_thread(generate_report.delay, "monthly_sales", 2025)
    print(f"  ✅ generate_report 结果: {await asyncio.to_thread(r2.get, timeout=30)}\n")

    r3 = await asyncio.to_thread(push_notification.delay, 1001, "您有新消息")
    print(f"  ✅ push_notification 结果: {await asyncio.to_thread(r3.get, timeout=30)}\n")

    r4 = await asyncio.to_thread(default_task.delay, "普通数据处理")
    print(f"  ✅ default_task 结果: {await asyncio.to_thread(r4.get, timeout=30)}\n")

    # Worker 启动说明
    print("── Worker 启动命令 ──")
    print("  💡 本示例需要 Worker 消费所有队列:")
    print("     celery -A examples.06_routing_and_queues.01_task_queues worker -l info -P solo -Q default,email_queue,report_queue,notification_queue")
    print()
    print("  💡 生产环境可为每个队列启动独立 Worker:")
    print("     celery -A myproj.celery_app:app worker -Q default              # 处理默认队列")
    print("     celery -A myproj.celery_app:app worker -Q email_queue          # 专门处理邮件")
    print("     celery -A myproj.celery_app:app worker -Q report_queue         # 专门处理报表")
    print("     celery -A myproj.celery_app:app worker -Q email_queue,default  # 同时处理多个队列")
    print("     celery -A myproj.celery_app:app worker -Q default -c 4         # 4 个并发 worker")


if __name__ == "__main__":
    asyncio.run(main())
