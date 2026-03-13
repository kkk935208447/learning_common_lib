"""
目标: 演示 Celery JSON 序列化约束，哪些类型安全、哪些会失败、以及解决方案
关键 API: task_serializer='json', json.dumps(), .isoformat()
Python 版本: 3.11+
运行方式 (两个终端):
  终端1 (worker):  cd src/learning_common_lib/redis_lession/celery教程与Redlock && uv run celery -A examples.02_task_definition.02_serialization worker --loglevel=info
  终端2 (client):  cd src/learning_common_lib/redis_lession/celery教程与Redlock && uv run python examples/02_task_definition/02_serialization.py
预期现象: JSON 安全类型正常传递，不安全类型触发异常并展示 workaround
生产提醒: 始终使用 JSON 序列化 (勿用 pickle)，复杂对象先转为 JSON 安全类型再传入任务
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from celery import Celery

# ── 1. 创建应用，强制 JSON 序列化 ──
app = Celery(
    "examples.02_task_definition.02_serialization",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)


# ── 2. 回显任务 ──
@app.task
def echo(data: Any) -> Any:
    """原样返回参数，用于测试序列化"""
    print(f"  📦 收到: {data!r} (类型: {type(data).__name__})")
    return data


# ── 3. JSON 安全类型测试 ──
async def test_json_safe() -> None:
    """str, int, float, list, dict, None, bool 都是 JSON 安全的"""
    print("── JSON 安全类型 ──")
    safe_values: list[tuple[str, Any]] = [
        ("str", "hello"),
        ("int", 42),
        ("float", 3.14),
        ("bool", True),
        ("None", None),
        ("list", [1, 2, 3]),
        ("dict", {"key": "value", "nested": {"a": 1}}),
    ]
    for type_name, value in safe_values:
        r = await asyncio.to_thread(echo.delay, value)
        result = await asyncio.to_thread(r.get, timeout=30)
        print(f"  ✅ {type_name:.<10} 传入={value!r:.<30} 返回={result!r}")
    print()


# ── 4. JSON 不安全类型测试 ──
async def test_json_unsafe() -> None:
    """datetime, set, 自定义对象等无法直接 JSON 序列化"""
    print("── JSON 不安全类型 ──")

    # datetime
    print("  🔸 datetime:")
    try:
        now = datetime.now(tz=timezone.utc)
        # json.dumps 会失败
        json.dumps(now)
    except TypeError as e:
        print(f"     ❌ json.dumps(datetime) 失败: {e}")

    # set
    print("  🔸 set:")
    try:
        json.dumps({1, 2, 3})
    except TypeError as e:
        print(f"     ❌ json.dumps(set) 失败: {e}")

    # 自定义对象
    print("  🔸 自定义对象:")

    class User:
        def __init__(self, name: str) -> None:
            self.name = name

    try:
        json.dumps(User("Alice"))
    except TypeError as e:
        print(f"     ❌ json.dumps(User) 失败: {e}")
    print()


# ── 5. Workaround: 转换为 JSON 安全类型 ──
@app.task
def process_event(event: dict[str, Any]) -> dict[str, Any]:
    """接收已序列化的事件数据"""
    # 在任务内部反序列化
    event["timestamp"] = datetime.fromisoformat(event["timestamp"])
    print(f"  📦 处理事件: {event}")
    # 返回时再转回 JSON 安全类型
    event["timestamp"] = event["timestamp"].isoformat()
    return event


async def test_workaround() -> None:
    """将不安全类型转为字符串后传递"""
    print("── Workaround: 序列化后传递 ──")

    # datetime → isoformat 字符串
    now = datetime.now(tz=timezone.utc)
    event = {
        "type": "user_login",
        "timestamp": now.isoformat(),  # 转为字符串
        "tags": list({1, 2, 3}),       # set → list
        "user": {"name": "Alice"},     # 自定义对象 → dict
    }
    r = await asyncio.to_thread(process_event.delay, event)
    result = await asyncio.to_thread(r.get, timeout=30)
    print(f"  ✅ 返回: {result}")
    print()

    # 验证 json.dumps 可以处理转换后的数据
    serialized = json.dumps(event, ensure_ascii=False)
    print(f"  ✅ json.dumps 成功: {serialized}")
    print()


# ── 6. 入口 ──
async def main() -> None:
    print("🚀 Celery JSON 序列化约束示例\n")

    await test_json_safe()
    await test_json_unsafe()
    await test_workaround()

    print("💡 黄金法则: 任务参数和返回值只用 str/int/float/bool/None/list/dict")
    print("💡 复杂对象在调用前序列化，在任务内反序列化")
    print("💡 永远不要在生产中使用 pickle 序列化 (安全风险)")


if __name__ == "__main__":
    asyncio.run(main())
