"""Idempotent Celery task discovery helpers for package mode and script mode."""

from __future__ import annotations

from celery import Celery


_TASKS_DISCOVERED = False


def iter_task_module_names() -> tuple[str, ...]:
    # 根据当前导入方式推导任务模块名，兼容包内运行和脚本目录运行。
    package_name = __package__
    if package_name:
        return (f"{package_name}.tasks",)
    return ("tasks",)


def autodiscover_demo_tasks(celery_app: Celery) -> None:
    global _TASKS_DISCOVERED

    if _TASKS_DISCOVERED:
        # 做成幂等方法后，API、worker、dispatcher 都可以放心重复调用。
        return

    # 同时兼容 `python -m package.module` 和 `cd demo && python script.py` 两种导入路径。
    for module_name in iter_task_module_names():
        # 直接导入任务模块比再引入 Celery autodiscover 目录约定更直观，适合这个 demo 规模。
        celery_app.loader.import_task_module(module_name)

    _TASKS_DISCOVERED = True
