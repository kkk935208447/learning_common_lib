"""
目标: 演示 FastAPI BackgroundTasks 在响应后执行异步任务
关键 API: APIRouter, BackgroundTasks, JSONResponse
Python 版本: 3.11+
运行命令: uv run python examples/06_background_streaming/01_background_tasks.py  (手动探索 /docs)
测试命令: uv run python examples/06_background_streaming/01_background_tasks_test.py
生产提醒: BackgroundTasks 适合轻量任务（发邮件、写日志），重任务用 Celery/arq
"""

import asyncio

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# 后台任务
# ---------------------------------------------------------------------------

_task_log: list[str] = []


async def send_notification(email: str, message: str) -> None:
    """模拟发送通知（异步）。"""
    await asyncio.sleep(0.1)
    log = f"已发送通知到 {email}: {message}"
    _task_log.append(log)
    print(f"  [后台] {log}")


def write_audit_log(action: str, user: str) -> None:
    """模拟写审计日志（同步函数也可以）。"""
    log = f"审计日志: {user} 执行了 {action}"
    _task_log.append(log)
    print(f"  [后台] {log}")


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["background_streaming"])


@router.post("/orders")
async def create_order(background_tasks: BackgroundTasks):
    background_tasks.add_task(send_notification, "user@example.com", "订单已创建")
    background_tasks.add_task(write_audit_log, "create_order", "user_1")
    return JSONResponse(content={"order_id": 1, "status": "created"})


@router.get("/task-log")
async def get_task_log():
    return JSONResponse(content={"log": _task_log})


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="01_background_tasks — 后台任务")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
