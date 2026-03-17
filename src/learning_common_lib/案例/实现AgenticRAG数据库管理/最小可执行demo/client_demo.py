"""HTTP smoke client that exercises the API after worker and API are up."""

from __future__ import annotations

import asyncio
from uuid import uuid4
from typing import Any

import httpx

try:
    from .config import get_settings
except ImportError:
    from config import get_settings


def print_section(title: str) -> None:
    # 输出分段标题，方便肉眼跟踪一整条 HTTP 烟雾测试链路。
    print(f"\n=== {title} ===")


async def wait_for_condition(
    client: httpx.AsyncClient,
    document_id: int,
    *,
    expected_document_status: str,
    expected_version_status: str,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        # 这里直接轮询文档详情，而不是读 Celery 状态；教学上更贴近“业务最终态”。
        response = await client.get(f"/documents/{document_id}")
        response.raise_for_status()
        payload = response.json()["data"]
        versions = payload["versions"]
        if versions:
            latest = versions[0]
            if (
                payload["lifecycle_status"] == expected_document_status
                and latest["visibility_status"] == expected_version_status
            ):
                return payload
        await asyncio.sleep(1)
    raise TimeoutError(
        f"等待 document={document_id} 进入状态 "
        f"{expected_document_status}/{expected_version_status} 超时"
    )


async def print_admin_stats(client: httpx.AsyncClient) -> None:
    # 统计接口能快速判断 Outbox 是否堆积、解析/索引是否出现失败。
    response = await client.get("/admin/stats")
    response.raise_for_status()
    print(response.json()["data"])


async def wait_for_api_ready(client: httpx.AsyncClient, timeout_seconds: int = 30) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        try:
            response = await client.get("/health")
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)
    raise TimeoutError("等待 FastAPI /health 就绪超时")


async def main() -> None:
    settings = get_settings()
    base_url = f"http://{settings.api_host}:{settings.api_port}"
    external_doc_key = f"employee-handbook-{uuid4().hex[:8]}"
    # 文本内容保持稳定，方便对比不同运行方式下的状态输出。
    file_bytes = (
        "第一章：请假流程。\n"
        "员工请假需要提前在系统中提交申请。\n"
        "第二章：报销流程。\n"
        "所有报销单据需在月底前提交。\n"
        "第三章：考勤规范。\n"
        "上班时间为上午九点。\n"
    ).encode("utf-8")

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        print_section("等待 API 就绪")
        await wait_for_api_ready(client)
        print({"api": "ready", "base_url": base_url})

        print_section("上传文档")
        response = await client.post(
            "/documents/upload",
            data={"external_doc_key": external_doc_key, "title": "员工手册"},
            files={"file": ("employee.txt", file_bytes, "text/plain")},
        )
        response.raise_for_status()
        upload_payload = response.json()["data"]
        print(upload_payload)

        document_id = upload_payload["document_id"]

        print_section("等待异步解析与索引完成")
        # 这里等到文档进入 ACTIVE，而不是只看单个 task 成功，能覆盖更多状态机问题。
        document_payload = await wait_for_condition(
            client,
            document_id,
            expected_document_status="ACTIVE",
            expected_version_status="ACTIVE",
        )
        print(document_payload)

        version_id = document_payload["active_version_id"]

        print_section("查看活动版本详情")
        response = await client.get(f"/versions/{version_id}")
        response.raise_for_status()
        print(response.json()["data"])

        print_section("查看管理统计")
        await print_admin_stats(client)

        print_section("手动触发 Janitor")
        # 正常情况下这里不会修复任何东西，这一步主要验证管理接口是否通。
        response = await client.post("/admin/janitor/run")
        response.raise_for_status()
        print(response.json()["data"])

        print_section("删除文档")
        response = await client.delete(f"/documents/{document_id}")
        response.raise_for_status()
        print(response.json())

        print_section("等待异步清理完成")
        document_payload = await wait_for_condition(
            client,
            document_id,
            expected_document_status="DELETED",
            expected_version_status="DELETED",
        )
        print(document_payload)

        print_section("查看清理后的管理统计")
        await print_admin_stats(client)


if __name__ == "__main__":
    asyncio.run(main())
