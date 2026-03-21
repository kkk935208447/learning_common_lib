"""Production-like integration test for FastAPI + Celery + MySQL + Redis."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from dataclasses import dataclass
from pathlib import Path

import httpx

try:
    from .config import get_settings
    from .domain.contracts import SearchSubmitRequest
    from .service_runtime import build_runtime_bundle, build_search_command_service
except ImportError:
    import sys
    from pathlib import Path

    demo_parent = Path(__file__).resolve().parent.parent
    if str(demo_parent) not in sys.path:
        sys.path.insert(0, str(demo_parent))
    from 最小可执行demo.config import get_settings
    from 最小可执行demo.domain.contracts import (
        SearchSubmitRequest,
    )
    from 最小可执行demo.service_runtime import (
        build_runtime_bundle,
        build_search_command_service,
    )


DEMO_ROOT = Path(__file__).resolve().parent
CASES_ROOT = DEMO_ROOT.parent.parent
UPSTREAM_INIT = CASES_ROOT / "实现AgenticRAG数据库管理" / "最小可执行demo" / "init_db.py"
DEEP_INIT = DEMO_ROOT / "init_db.py"
SEED = DEMO_ROOT / "seed_demo_kb.py"
API_SCRIPT = DEMO_ROOT / "api.py"
CELERY_APP = "celery_app:celery_app"


@dataclass(slots=True)
class ManagedProcess:
    name: str
    process: asyncio.subprocess.Process
    log_path: Path


def base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = os.environ.get("UV_CACHE_DIR", "/tmp/uv-cache")
    env["DEEPSEARCH_DEMO_CELERY_EAGER"] = "0"
    env.setdefault("MIN_RAG_CELERY_EAGER", "1")
    return env


async def run_command(name: str, *args: str, env: dict[str, str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(DEMO_ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    text = output.decode("utf-8", errors="ignore")
    if process.returncode != 0:
        raise RuntimeError(f"{name} failed with code {process.returncode}:\n{text}")
    if text.strip():
        print(f"[{name}]")
        print(text.strip())


async def start_process(name: str, *args: str, env: dict[str, str], log_dir: Path) -> ManagedProcess:
    log_path = log_dir / f"{name}.log"
    log_file = open(log_path, "w", encoding="utf-8")
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(DEMO_ROOT),
        env=env,
        stdout=log_file,
        stderr=asyncio.subprocess.STDOUT,
    )
    return ManagedProcess(name=name, process=process, log_path=log_path)


async def stop_process(item: ManagedProcess) -> None:
    if item.process.returncode is not None:
        return
    item.process.send_signal(signal.SIGINT)
    try:
        await asyncio.wait_for(item.process.wait(), timeout=5)
    except asyncio.TimeoutError:
        item.process.terminate()
        try:
            await asyncio.wait_for(item.process.wait(), timeout=5)
        except asyncio.TimeoutError:
            item.process.kill()
            await item.process.wait()


async def wait_for_health(base_url: str, timeout_s: int = 30) -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        for _ in range(timeout_s * 2):
            try:
                resp = await client.get(f"{base_url}/api/v1/health")
                if resp.status_code == 200:
                    return
            except Exception:
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError("API health check timed out")


async def poll_snapshot(base_url: str, request_id: str, *, timeout_s: int = 60) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        for _ in range(timeout_s):
            resp = await client.get(f"{base_url}/api/v1/search/{request_id}")
            resp.raise_for_status()
            snapshot = resp.json()["data"]
            if snapshot["status"] in {"COMPLETED", "DEGRADED", "FAILED", "WAITING_CLARIFICATION"}:
                return snapshot
            await asyncio.sleep(1)
    raise RuntimeError(f"snapshot polling timed out for {request_id}")


async def read_sse_until_terminal(base_url: str, request_id: str, *, last_event_id: int | None = None) -> list[dict]:
    headers: dict[str, str] = {}
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    events: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream("GET", f"{base_url}/api/v1/search/{request_id}/events", headers=headers) as resp:
            resp.raise_for_status()
            current: dict[str, str] = {}
            async for line in resp.aiter_lines():
                if line == "":
                    if current:
                        events.append(json.loads(current["data"]))
                        current = {}
                        if events[-1]["event"] in {"task_completed", "task_degraded", "task_failed"}:
                            break
                    continue
                if ": " in line:
                    key, value = line.split(": ", 1)
                    current[key] = value
    return events


async def read_sse_until_clarify(base_url: str, request_id: str) -> list[dict]:
    events: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream("GET", f"{base_url}/api/v1/search/{request_id}/events") as resp:
            resp.raise_for_status()
            current: dict[str, str] = {}
            async for line in resp.aiter_lines():
                if line == "":
                    if current:
                        payload = json.loads(current["data"])
                        events.append(payload)
                        current = {}
                        if payload["event"] in {"clarification_requested", "task_waiting_clarification"}:
                            break
                    continue
                if ": " in line:
                    key, value = line.split(": ", 1)
                    current[key] = value
    return events


def assert_subsequence(events: list[str], expected: list[str]) -> None:
    cursor = 0
    for event in events:
        if cursor < len(expected) and event == expected[cursor]:
            cursor += 1
    if cursor != len(expected):
        raise AssertionError(f"expected subsequence {expected}, got {events}")


async def test_http_completion(base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        submit = await client.post(
            f"{base_url}/api/v1/search",
            json={
                "session_id": "sess_integration_http",
                "query": "请帮我整理公司近 90 天差旅报销规则的变化",
                "kb_code": "default",
                "scope_json": None,
            },
        )
        submit.raise_for_status()
        request_id = submit.json()["data"]["request_id"]
    snapshot = await poll_snapshot(base_url, request_id)
    if snapshot["status"] != "COMPLETED":
        raise AssertionError(f"HTTP completion test expected COMPLETED, got {snapshot['status']}")
    return {"request_id": request_id, "final_status": snapshot["status"]}


async def test_sse_sequence(base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        submit = await client.post(
            f"{base_url}/api/v1/search",
            json={
                "session_id": "sess_integration_sse",
                "query": "请帮我整理公司近 90 天差旅报销规则的变化",
                "kb_code": "default",
                "scope_json": None,
            },
        )
        submit.raise_for_status()
        request_id = submit.json()["data"]["request_id"]
    events = await read_sse_until_terminal(base_url, request_id)
    names = [item["event"] for item in events]
    assert_subsequence(
        names,
        [
            "task_submitted",
            "task_planning_started",
            "plan_activated",
            "subtask_claimed",
            "subtask_started",
            "subtask_completed",
            "task_completed",
        ],
    )
    replay_from = events[3]["id"] if len(events) > 3 else events[0]["id"]
    replay = await read_sse_until_terminal(base_url, request_id, last_event_id=replay_from)
    replay_names = [item["event"] for item in replay]
    if not replay_names or replay_names[0] == names[0]:
        raise AssertionError("SSE replay did not continue from Last-Event-ID")
    return {"request_id": request_id, "event_count": len(events), "replay_count": len(replay)}


async def test_clarify_flow(base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        submit = await client.post(
            f"{base_url}/api/v1/search",
            json={
                "session_id": "sess_integration_clarify",
                "query": "请帮我整理差旅报销规则的变化",
                "kb_code": "default",
                "scope_json": None,
            },
        )
        submit.raise_for_status()
        request_id = submit.json()["data"]["request_id"]
        snapshot_data = None
        for _ in range(30):
            snapshot = await client.get(f"{base_url}/api/v1/search/{request_id}")
            snapshot.raise_for_status()
            snapshot_data = snapshot.json()["data"]
            if snapshot_data["status"] == "WAITING_CLARIFICATION":
                break
            if snapshot_data["status"] in {"COMPLETED", "DEGRADED", "FAILED"}:
                raise AssertionError(
                    f"Clarify test expected WAITING_CLARIFICATION, got terminal status {snapshot_data['status']}"
                )
            await asyncio.sleep(1)
        if snapshot_data is None or snapshot_data["status"] != "WAITING_CLARIFICATION":
            raise AssertionError("Clarify test timed out waiting for WAITING_CLARIFICATION")
        clarify_request = snapshot_data["clarification_request"]

    events = await read_sse_until_clarify(base_url, request_id)
    event_names = [item["event"] for item in events]
    assert_subsequence(event_names, ["task_submitted", "task_planning_started", "clarification_requested"])

    async with httpx.AsyncClient(timeout=30) as client:
        answer = await client.post(
            f"{base_url}/api/v1/search/{request_id}/clarification",
            json={"selected_option_id": clarify_request["default_option_id"]},
        )
        answer.raise_for_status()
    final_snapshot = None
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(60):
            resp = await client.get(f"{base_url}/api/v1/search/{request_id}")
            resp.raise_for_status()
            final_snapshot = resp.json()["data"]
            if final_snapshot["status"] in {"COMPLETED", "DEGRADED", "FAILED"}:
                break
            await asyncio.sleep(1)
    if final_snapshot is None:
        raise AssertionError("Clarify flow did not produce a final snapshot")
    if final_snapshot["status"] != "COMPLETED":
        raise AssertionError(f"Clarify flow expected COMPLETED, got {final_snapshot['status']}")
    return {"request_id": request_id, "clarify_events": event_names, "final_status": final_snapshot["status"]}


async def test_offline_submit() -> dict:
    service = build_search_command_service(use_task_engine=True)
    runtime = build_runtime_bundle(use_task_engine=True)
    accepted = await service.submit_search(
        SearchSubmitRequest(
            session_id="sess_integration_offline",
            query="请帮我整理公司近 90 天差旅报销规则的变化",
            kb_code="default",
            scope_json=None,
        )
    )
    request_id = accepted.request_id
    final_snapshot = None
    for _ in range(60):
        async with runtime.session_factory() as session:
            final_snapshot = await runtime.progress_service.build_snapshot(session, request_id)
        if final_snapshot.status in {"COMPLETED", "DEGRADED", "FAILED", "WAITING_CLARIFICATION"}:
            break
        await asyncio.sleep(1)
    if final_snapshot is None or final_snapshot.status != "COMPLETED":
        raise AssertionError(f"Offline submit expected COMPLETED, got {getattr(final_snapshot, 'status', None)}")
    return {"request_id": request_id, "final_status": final_snapshot.status}


async def main() -> None:
    port = 8097
    base_url = f"http://127.0.0.1:{port}"
    log_dir = DEMO_ROOT / ".runtime" / "integration_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    env = base_env()
    env["DEEPSEARCH_DEMO_API_PORT"] = str(port)

    await run_command("upstream_init", "uv", "run", "python", str(UPSTREAM_INIT), env=env)
    await run_command("deep_init", "uv", "run", "python", str(DEEP_INIT), env=env)
    await run_command("seed_demo_kb", "uv", "run", "python", str(SEED), env=env)
    await run_command("purge_queue", "uv", "run", "celery", "-A", CELERY_APP, "purge", "-f", env=env)

    worker = await start_process(
        "worker",
        "uv",
        "run",
        "celery",
        "-A",
        CELERY_APP,
        "worker",
        "-Q",
        "orchestrate_jobs,subtask_jobs,persist_jobs,maintenance_jobs",
        "-l",
        "INFO",
        env=env,
        log_dir=log_dir,
    )
    beat = await start_process(
        "beat",
        "uv",
        "run",
        "celery",
        "-A",
        CELERY_APP,
        "beat",
        "-l",
        "INFO",
        env=env,
        log_dir=log_dir,
    )
    api = await start_process(
        "api",
        "uv",
        "run",
        "python",
        str(API_SCRIPT),
        env=env,
        log_dir=log_dir,
    )

    try:
        await wait_for_health(base_url)
        await asyncio.sleep(2)
        summary = {
            "http_completion": await test_http_completion(base_url),
            "sse_sequence": await test_sse_sequence(base_url),
            "clarify_flow": await test_clarify_flow(base_url),
            "offline_submit": await test_offline_submit(),
            "logs": {
                "worker": str(worker.log_path),
                "beat": str(beat.log_path),
                "api": str(api.log_path),
            },
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        await stop_process(api)
        await stop_process(worker)
        await stop_process(beat)


if __name__ == "__main__":
    asyncio.run(main())
