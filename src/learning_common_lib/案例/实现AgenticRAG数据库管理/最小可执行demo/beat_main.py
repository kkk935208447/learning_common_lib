from __future__ import annotations

try:
    from .celery_app import celery_app
    from .tasks import ensure_tasks_registered
except ImportError:
    from celery_app import celery_app
    from tasks import ensure_tasks_registered


if __name__ == "__main__":
    ensure_tasks_registered()
    celery_app.start(["beat", "-l", "info"])
