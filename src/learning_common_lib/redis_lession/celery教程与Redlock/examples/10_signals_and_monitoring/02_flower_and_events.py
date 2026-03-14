"""
目标: Flower 监控与事件系统 — 任务事件、自定义事件、监控模式
关键 API: task_send_sent_event, worker_send_task_events, Flower, events
Python 版本: 3.11+
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
运行命令:
  终端 1 (启动 Worker):
    celery -A examples.10_signals_and_monitoring.02_flower_and_events worker -l info -P solo
  终端 2 (运行示例):
    uv run python examples/10_signals_and_monitoring/02_flower_and_events.py
  (从 src/learning_common_lib/redis_lession/celery教程与Redlock 目录)
预期现象: 打印 Flower 配置、事件类型、监控命令，演示事件配置
生产提醒: Flower 需独立部署，建议与 worker 共用稳定 app 入口
    （如 celery -A myproj.celery_app:app flower），并配合 Prometheus + Grafana 做长期监控
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from celery import Celery

# ── 1. 创建 Celery 应用并配置事件 ──
app = Celery(
    "examples.10_signals_and_monitoring.02_flower_and_events",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)

app.conf.update(
    # 事件配置
    task_send_sent_event=True,       # 任务发送时发出 task-sent 事件
    worker_send_task_events=True,    # worker 发送任务相关事件
    worker_hijack_root_logger=False, # 不劫持根日志器
    # 事件相关
    event_queue_ttl=5.0,             # 事件队列 TTL (秒)
    event_queue_expires=60.0,        # 事件队列过期时间 (秒)
)


# ── 2. 定义示例任务 ──
@app.task(bind=True)
def monitored_task(self: Any, duration: int = 1) -> dict[str, str]:
    """被监控的任务"""
    print(f"  ⚙️ 执行任务: id={self.request.id}, duration={duration}s")
    return {"status": "completed", "duration": duration}


@app.task(bind=True)
def task_with_progress(self: Any, total: int = 100) -> dict[str, Any]:
    """带进度上报的任务"""
    print(f"  📊 开始处理 {total} 个条目")
    for step in [25, 50, 75, 100]:
        # update_state 会发送 task-progress 事件
        self.update_state(
            state="PROGRESS",
            meta={"current": step, "total": total, "percent": step},
        )
        print(f"  📈 进度: {step}%")
        time.sleep(0.5)
    return {"status": "done", "processed": total}


# ── 3. 入口 ──
async def main() -> None:
    print("🚀 Celery Flower 与事件监控示例\n")

    # Flower 安装与启动
    print("── Flower 安装与启动 ──")
    print("  💡 安装: pip install flower")
    print("  💡 启动: celery -A myproj.celery_app:app flower")
    print("  💡 指定端口: celery -A myproj.celery_app:app flower --port=5555")
    print("  💡 带认证: celery -A myproj.celery_app:app flower --basic-auth=admin:password")
    print("  💡 访问: http://localhost:5555")
    print()

    # Flower 功能概览
    print("── Flower 功能概览 ──")
    features = [
        ("Dashboard", "实时查看 worker 状态、活跃任务数、处理速率"),
        ("Tasks", "查看任务列表、状态、结果、执行时间、重试次数"),
        ("Workers", "查看 worker 详情、并发数、已处理任务数"),
        ("Broker", "查看队列长度、消息数量"),
        ("Monitor", "实时任务事件流、成功/失败率图表"),
        ("API", "REST API 支持远程管理 (关闭 worker、撤销任务等)"),
    ]
    for name, desc in features:
        print(f"  🖥️ {name:<12} {desc}")
    print()

    # 事件类型
    print("── Celery 事件类型 ──")
    event_types = [
        ("task-sent", "任务已发送到 broker (需 task_send_sent_event=True)"),
        ("task-received", "worker 收到任务"),
        ("task-started", "worker 开始执行任务"),
        ("task-succeeded", "任务执行成功"),
        ("task-failed", "任务执行失败"),
        ("task-rejected", "任务被拒绝"),
        ("task-revoked", "任务被撤销"),
        ("task-retried", "任务重试"),
        ("worker-online", "worker 上线"),
        ("worker-heartbeat", "worker 心跳"),
        ("worker-offline", "worker 下线"),
    ]
    for event, desc in event_types:
        print(f"  📡 {event:<20} {desc}")
    print()

    # 当前事件配置
    print("── 当前事件配置 ──")
    print(f"  📋 task_send_sent_event:    {app.conf.task_send_sent_event}")
    print(f"  📋 worker_send_task_events: {app.conf.worker_send_task_events}")
    print(f"  📋 event_queue_ttl:         {app.conf.event_queue_ttl}s")
    print(f"  📋 event_queue_expires:     {app.conf.event_queue_expires}s")
    print()

    # 执行带进度的任务
    print("── 执行带进度上报的任务 ──")
    r1 = await asyncio.to_thread(task_with_progress.delay, 200)
    # 轮询进度 (update_state 写入 Redis backend，客户端可读取)
    for _ in range(20):
        meta = await asyncio.to_thread(lambda: r1.info)
        state = await asyncio.to_thread(lambda: r1.state)
        if state == "PROGRESS":
            progress = meta.get("percent", "?") if isinstance(meta, dict) else "?"
            print(f"  📈 进度: {progress}%")
        elif state == "SUCCESS":
            break
        await asyncio.sleep(0.5)
    result = await asyncio.to_thread(r1.get, timeout=30)
    print(f"  ✅ 结果: {result}\n")

    # 执行普通监控任务
    print("── 执行普通监控任务 ──")
    r2 = await asyncio.to_thread(monitored_task.delay, 3)
    print(f"  ✅ 结果: {await asyncio.to_thread(r2.get, timeout=30)}\n")

    # CLI 监控命令
    print("── CLI 监控命令 ──")
    print("  💡 celery -A myproj.celery_app:app events               # 实时事件流 (curses 界面)")
    print("  💡 celery -A myproj.celery_app:app events --dump        # 事件转储到 stdout")
    print("  💡 celery -A myproj.celery_app:app events -c camera     # 自定义事件相机")
    print("  💡 celery -A myproj.celery_app:app inspect active       # 查看活跃任务")
    print("  💡 celery -A myproj.celery_app:app inspect reserved     # 查看预留任务")
    print("  💡 celery -A myproj.celery_app:app inspect stats        # 查看 worker 统计")
    print("  💡 celery -A myproj.celery_app:app control rate_limit task_name 10/m  # 限速")
    print()

    # Prometheus + Grafana 集成
    print("── 生产监控建议 ──")
    print("  💡 Flower + Prometheus exporter: flower --prometheus-addr=0.0.0.0:9090")
    print("  💡 celery-exporter: 独立的 Prometheus exporter")
    print("  💡 Sentry: 集成 sentry-sdk[celery] 捕获任务异常")
    print("  💡 自定义: 在信号处理器中推送指标到 StatsD/Datadog")


if __name__ == "__main__":
    asyncio.run(main())
