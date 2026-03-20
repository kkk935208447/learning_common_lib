"""Small HTTP client for the FastAPI demo."""

from __future__ import annotations

import asyncio

import httpx

try:
    from .config import get_settings
except ImportError:
    import sys
    from pathlib import Path

    demo_parent = Path(__file__).resolve().parent.parent
    if str(demo_parent) not in sys.path:
        sys.path.insert(0, str(demo_parent))
    from 最小可执行demo.config import get_settings


async def main() -> None:
    settings = get_settings()
    base_url = f"http://{settings.api_host}:{settings.api_port}"
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        submit = await client.post(
            "/api/v1/search",
            json={
                "session_id": "sess_http_demo",
                "query": "请帮我整理公司近 90 天差旅报销规则的变化",
                "kb_code": "default",
                "scope_json": None,
            },
        )
        submit.raise_for_status()
        payload = submit.json()["data"]
        print("submit:", payload)
        request_id = payload["request_id"]

        snapshot = await client.get(f"/api/v1/search/{request_id}")
        snapshot.raise_for_status()
        print("snapshot:", snapshot.json()["data"])


if __name__ == "__main__":
    asyncio.run(main())
