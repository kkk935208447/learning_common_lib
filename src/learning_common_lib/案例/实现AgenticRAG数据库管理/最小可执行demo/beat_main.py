"""Script entry that starts Celery Beat for periodic dispatcher and janitor jobs."""

from __future__ import annotations

try:
    from .celery_app import celery_app
except ImportError:
    from celery_app import celery_app


if __name__ == "__main__":
    # 脚本入口只做一件事：用和 CLI 一致的 app 启动 Beat，方便本地教学演示。
    # 保持这里极简，读者看到脚本就能直接对应到 `celery ... beat -l info`。
    celery_app.start(["beat", "-l", "info"])
