"""
目标: 演示 yield 依赖——模拟数据库连接的获取与释放
关键 API: APIRouter, Depends + yield, HTTPException
Python 版本: 3.11+
运行命令: uv run python examples/03_dependency_injection/02_yield_depends.py  (手动探索 /docs)
测试命令: uv run python examples/03_dependency_injection/02_yield_depends_test.py
生产提醒: yield 依赖是 FastAPI 管理资源生命周期的核心模式，等价于 contextmanager
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# 模拟数据库连接
# ---------------------------------------------------------------------------


class FakeDBConnection:
    def __init__(self, conn_id: int):
        self.conn_id = conn_id
        self.closed = False

    def query(self, sql: str) -> str:
        return f"[conn-{self.conn_id}] result of: {sql}"

    def close(self) -> None:
        self.closed = True


_conn_counter = 0


async def get_db():
    """yield 依赖：请求开始时获取连接，结束时释放。"""
    global _conn_counter
    _conn_counter += 1
    conn = FakeDBConnection(_conn_counter)
    print(f"  → 获取连接 conn-{conn.conn_id}")
    try:
        yield conn
    finally:
        conn.close()
        print(f"  ← 释放连接 conn-{conn.conn_id} (closed={conn.closed})")


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["dependency_injection"])


@router.get("/data")
async def get_data(db: FakeDBConnection = Depends(get_db)):
    result = db.query("SELECT * FROM data")
    return JSONResponse(content={"result": result})


@router.get("/error")
async def get_error(db: FakeDBConnection = Depends(get_db)):
    """即使抛异常，yield 依赖的 finally 仍会执行。"""
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="模拟错误"
    )


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="02_yield_depends — yield 依赖")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
