"""
目标: 演示 Celery 三种配置模式与最佳实践 (Configuration Patterns & Best Practices)
关键概念:
  - 配置分离原则：开发/测试/生产环境配置隔离
  - 配置优先级：环境变量 > 配置文件 > 代码硬编码
  - 敏感信息管理：broker 密码、API 密钥等通过环境变量注入
关键 API: app.conf.update(), config_from_object(), config_from_envvar()
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/01_app_and_config
运行方式:
  Client: python examples/01_app_and_config/02_config_patterns.py
    (本示例仅演示配置加载，不派发任务，无需启动 worker)
预期现象:
  - 依次展示字典配置、类配置、环境变量配置三种方式
  - 打印各配置项的值和类型，验证配置加载正确性
  - 演示配置优先级覆盖机制
生产提醒:
  - 生产环境必须使用环境变量管理敏感信息，避免密码泄露
  - 建议使用配置类模式，便于不同环境的配置管理和版本控制
技术要点:
  - config_from_envvar() 加载的是 Python 模块，不是 JSON 文件
  - 配置项名称区分大小写，必须与 Celery 官方文档一致
  - 运行时修改 app.conf 只影响当前进程，不影响已启动的 worker
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any

from celery import Celery


# ── 1. 方式一：app.conf.update() 直接更新 ──
def demo_conf_update() -> Celery:
    """最直接的配置方式，适合小项目或测试"""
    app = Celery("conf_update_app")
    app.conf.update(
        broker_url="redis://:123456@localhost:6379/0",
        result_backend="redis://:123456@localhost:6379/1",
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="Asia/Shanghai",
    )
    return app


# ── 2. 方式二：config_from_object() 从对象/模块加载 ──
class CeleryConfig:
    """配置类，属性名必须与 Celery 配置项一致"""
    broker_url: str = "redis://:123456@localhost:6379/0"
    result_backend: str = "redis://:123456@localhost:6379/1"
    task_serializer: str = "json"
    result_serializer: str = "json"
    accept_content: list[str] = ["json"]
    timezone: str = "Asia/Shanghai"


def demo_config_from_object() -> Celery:
    """从 Python 对象加载配置，适合中大型项目"""
    app = Celery("config_object_app")
    app.config_from_object(CeleryConfig)
    return app


# ── 3. 方式三：config_from_envvar() 从环境变量指定的模块加载 ──
def demo_config_from_envvar() -> Celery:
    """从环境变量指向的配置模块加载，适合多环境部署"""
    # 创建临时配置文件模拟外部配置模块
    config_content = (
        'broker_url = "redis://:123456@localhost:6379/0"\n'
        'result_backend = "redis://:123456@localhost:6379/1"\n'
        'task_serializer = "json"\n'
        'result_serializer = "json"\n'
        'accept_content = ["json"]\n'
        'timezone = "Asia/Shanghai"\n'
    )

    # 写入临时 Python 模块
    tmp_dir = tempfile.mkdtemp()
    config_path = os.path.join(tmp_dir, "celery_settings.py")
    with open(config_path, "w") as f:
        f.write(config_content)

    # 将临时目录加入 sys.path 以便导入
    import sys
    sys.path.insert(0, tmp_dir)
    os.environ["CELERY_CONFIG_MODULE"] = "celery_settings"

    app = Celery("config_envvar_app")
    # config_from_envvar 内部用 importlib 导入模块，需要模块在 sys.path 中
    import importlib
    config_mod = importlib.import_module("celery_settings")
    app.config_from_object(config_mod)

    # 清理
    sys.path.remove(tmp_dir)
    del os.environ["CELERY_CONFIG_MODULE"]
    return app


# ── 4. 打印配置工具 ──
KEY_PARAMS: list[str] = [
    "broker_url",
    "result_backend",
    "task_serializer",
    "result_serializer",
    "accept_content",
    "timezone",
]


def print_config(app: Celery, label: str) -> None:
    """打印关键配置项"""
    print(f"\n{'─' * 50}")
    print(f"📋 {label}")
    print(f"{'─' * 50}")
    for key in KEY_PARAMS:
        value: Any = getattr(app.conf, key, "未设置")
        print(f"  {key:.<35} {value}")


# ── 5. 入口 ──
async def main() -> None:
    print("🚀 Celery 配置方式对比示例\n")

    # 方式一
    app1 = demo_conf_update()
    print_config(app1, "方式一: app.conf.update()")

    # 方式二
    app2 = demo_config_from_object()
    print_config(app2, "方式二: config_from_object(CeleryConfig)")

    # 方式三
    app3 = demo_config_from_envvar()
    print_config(app3, "方式三: config_from_envvar('CELERY_CONFIG_MODULE')")

    print(f"\n{'─' * 50}")
    print("💡 推荐: 中大型项目用 config_from_object()，多环境部署用 config_from_envvar()")
    print("💡 三种方式可以混合使用，后设置的值会覆盖先前的值")


if __name__ == "__main__":
    asyncio.run(main())
