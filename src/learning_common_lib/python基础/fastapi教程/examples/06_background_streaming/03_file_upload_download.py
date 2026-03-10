"""
目标: 演示文件上传 (UploadFile) 和文件下载 (FileResponse)
关键 API: APIRouter, UploadFile, File, FileResponse, HTTPException
Python 版本: 3.11+
运行命令: uv run python examples/06_background_streaming/03_file_upload_download.py  (手动探索 /docs)
测试命令: uv run python examples/06_background_streaming/03_file_upload_download_test.py
生产提醒: 大文件上传用分块读取 (file.read(chunk_size))，避免内存溢出
"""

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

# ---------------------------------------------------------------------------
# 临时存储目录
# ---------------------------------------------------------------------------

_upload_dir = Path(tempfile.mkdtemp())

# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["background_streaming"])


@router.post("/upload")
async def upload_file(file: UploadFile = File(description="要上传的文件")):
    dest = _upload_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)
    return JSONResponse(content={
        "filename": file.filename,
        "size": len(content),
        "content_type": file.content_type,
    })


@router.get("/download/{filename}")
async def download_file(filename: str):
    path = _upload_dir / filename
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在"
        )
    return FileResponse(path, filename=filename)


@router.get("/files")
async def list_files():
    files = [f.name for f in _upload_dir.iterdir() if f.is_file()]
    return JSONResponse(content={"files": files})


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="03_file_upload_download — 文件上传下载")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
