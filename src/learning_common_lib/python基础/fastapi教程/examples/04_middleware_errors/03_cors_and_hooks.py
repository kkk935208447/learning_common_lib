"""
目标: 演示 CORS 配置和 lifespan 上下文管理器（启动/关闭事件）
关键 API: APIRouter, CORSMiddleware, asynccontextmanager, app.state, Request
Python 版本: 3.11+
运行命令: uv run python examples/04_middleware_errors/03_cors_and_hooks.py  (手动探索 /docs)
测试命令: uv run python examples/04_middleware_errors/03_cors_and_hooks_test.py
生产提醒: lifespan 替代了已废弃的 on_event("startup"/"shutdown")，是推荐方式
"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# lifespan 上下文管理器
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化，关闭时清理。"""
    app.state.cache = {"config": "loaded"}
    print("  [lifespan] 启动：缓存已初始化")
    yield
    app.state.cache.clear()
    print("  [lifespan] 关闭：缓存已清理")


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["middleware_errors"])


@router.get("/config")
async def get_config(request: Request):
    """读取 lifespan 中初始化的缓存。"""
    cache = getattr(request.app.state, "cache", {})
    return JSONResponse(content={"cache": cache})


# ---------------------------------------------------------------------------
# 创建 app 的工厂函数（测试文件调用）
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """组装 app：lifespan + CORS + router。"""
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


if __name__ == "__main__":
    import uvicorn

    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8000)
