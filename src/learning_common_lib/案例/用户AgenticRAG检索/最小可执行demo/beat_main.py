"""Script entrypoint for running Celery beat locally."""

from __future__ import annotations

try:
    from .celery_app import celery_app
except ImportError:
    import sys
    from pathlib import Path

    demo_parent = Path(__file__).resolve().parent.parent
    if str(demo_parent) not in sys.path:
        sys.path.insert(0, str(demo_parent))
    from 最小可执行demo.celery_app import celery_app


if __name__ == "__main__":
    celery_app.Beat(loglevel="INFO").run()
