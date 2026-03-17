"""Script entry that starts the demo Celery worker with the recommended queues."""

from __future__ import annotations

try:
    from .celery_app import celery_app
except ImportError:
    from celery_app import celery_app


if __name__ == "__main__":
    # worker_main 主要服务“直接运行脚本”的读者，不要求先记住 Celery CLI 参数。
    # 这个脚本本质上只是把 CLI 参数写成了 Python 入口，方便不熟 Celery CLI 的读者直接运行。
    celery_app.worker_main(
        [
            "worker",
            "-l",
            "info",
            "-P",
            "prefork",
            "-c",
            "2",
            "-Q",
            # 这里保留展开后的队列字符串，读 README 时能直接和启动命令对上。
            "parse_jobs,index_jobs,clean_jobs,repair_jobs,housekeeping_jobs",
        ]
    )
