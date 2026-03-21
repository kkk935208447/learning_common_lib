"""Production-like integration test for FastAPI + Celery + MySQL + Redis."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TextIO

import httpx
from sqlalchemy import select

try:
    from .application.common import build_request_id, utcnow
    from .config import get_settings
    from .domain.contracts import SearchSubmitRequest
    from .service_runtime import (
        build_global_graph_service_from_bundle,
        build_maintenance_service,
        build_runtime_bundle,
        build_search_command_service,
        build_subtask_graph_service,
        close_runtime_bundle,
    )
    from .infrastructure.models import EvidenceCard, SearchTask, SessionTurn, Subtask, SubtaskRun, TaskEvent
except ImportError:
    import sys
    from pathlib import Path

    demo_parent = Path(__file__).resolve().parent.parent
    if str(demo_parent) not in sys.path:
        sys.path.insert(0, str(demo_parent))
    from 最小可执行demo.application.common import build_request_id, utcnow
    from 最小可执行demo.config import get_settings
    from 最小可执行demo.domain.contracts import (
        SearchSubmitRequest,
    )
    from 最小可执行demo.service_runtime import (
        build_global_graph_service_from_bundle,
        build_maintenance_service,
        build_runtime_bundle,
        build_search_command_service,
        build_subtask_graph_service,
        close_runtime_bundle,
    )
    from 最小可执行demo.infrastructure.models import EvidenceCard, SearchTask, SessionTurn, Subtask, SubtaskRun, TaskEvent


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
    log_file: TextIO


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
    return ManagedProcess(name=name, process=process, log_path=log_path, log_file=log_file)


async def stop_process(item: ManagedProcess) -> None:
    if item.process.returncode is not None:
        item.log_file.close()
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
    finally:
        item.log_file.close()


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


async def read_single_sse_event(
    base_url: str,
    request_id: str,
    *,
    last_event_id: int | None = None,
) -> dict:
    headers: dict[str, str] = {}
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream("GET", f"{base_url}/api/v1/search/{request_id}/events", headers=headers) as resp:
            resp.raise_for_status()
            current: dict[str, str] = {}
            async for line in resp.aiter_lines():
                if line == "":
                    if current:
                        return json.loads(current["data"])
                    continue
                if ": " in line:
                    key, value = line.split(": ", 1)
                    current[key] = value
    raise AssertionError("SSE stream closed before yielding an event")


def assert_subsequence(events: list[str], expected: list[str]) -> None:
    cursor = 0
    for event in events:
        if cursor < len(expected) and event == expected[cursor]:
            cursor += 1
    if cursor != len(expected):
        raise AssertionError(f"expected subsequence {expected}, got {events}")


async def list_event_names(request_id: str) -> list[str]:
    runtime = build_runtime_bundle(use_task_engine=True)
    async with runtime.session_factory() as session:
        task = await session.scalar(select(SearchTask).where(SearchTask.request_id == request_id))
        if task is None:
            return []
        events = list(
            (
                await session.scalars(
                    select(TaskEvent).where(TaskEvent.task_id == task.id).order_by(TaskEvent.id.asc())
                )
            ).all()
        )
    return [event.event_type for event in events]


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


async def test_sse_invalid_last_event_id(base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        submit = await client.post(
            f"{base_url}/api/v1/search",
            json={
                "session_id": "sess_integration_bad_last_id",
                "query": "请帮我整理公司近 90 天差旅报销规则的变化",
                "kb_code": "default",
                "scope_json": None,
            },
        )
        submit.raise_for_status()
        request_id = submit.json()["data"]["request_id"]
        resp = await client.get(
            f"{base_url}/api/v1/search/{request_id}/events",
            headers={"Last-Event-ID": "abc"},
        )
    if resp.status_code != 400:
        raise AssertionError(f"Invalid Last-Event-ID should return 400, got {resp.status_code}: {resp.text}")
    payload = resp.json()
    if payload.get("code") != "VALIDATION_ERROR":
        raise AssertionError(f"Invalid Last-Event-ID should return VALIDATION_ERROR, got {payload}")
    return {"request_id": request_id, "status_code": resp.status_code}


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
    all_event_names = await list_event_names(request_id)
    planning_started_count = all_event_names.count("task_planning_started")
    if planning_started_count != 1:
        raise AssertionError(f"Clarify flow expected exactly one task_planning_started, got {planning_started_count}")
    return {
        "request_id": request_id,
        "clarify_events": event_names,
        "planning_started_count": planning_started_count,
        "final_status": final_snapshot["status"],
    }


async def test_expired_clarify_defaults(base_url: str) -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    async with httpx.AsyncClient(timeout=30) as client:
        submit = await client.post(
            f"{base_url}/api/v1/search",
            json={
                "session_id": "sess_integration_expired_clarify",
                "query": "请帮我整理差旅报销规则的变化",
                "kb_code": "default",
                "scope_json": None,
            },
        )
        submit.raise_for_status()
        request_id = submit.json()["data"]["request_id"]

    snapshot_data = None
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(30):
            snapshot = await client.get(f"{base_url}/api/v1/search/{request_id}")
            snapshot.raise_for_status()
            snapshot_data = snapshot.json()["data"]
            if snapshot_data["status"] == "WAITING_CLARIFICATION":
                break
            await asyncio.sleep(1)
    if snapshot_data is None or snapshot_data["status"] != "WAITING_CLARIFICATION":
        raise AssertionError("Expired clarify test timed out waiting for WAITING_CLARIFICATION")

    clarify_request = snapshot_data["clarification_request"]
    default_option_id = clarify_request["default_option_id"]
    fallback_option_id = next(
        option["id"] for option in clarify_request["options"] if option["id"] != default_option_id
    )
    expired_at = utcnow() - timedelta(minutes=1)

    async with runtime.session_factory() as session:
        async with session.begin():
            task = await session.scalar(select(SearchTask).where(SearchTask.request_id == request_id).with_for_update())
            if task is None:
                raise AssertionError("Expired clarify test task missing")
            control_json = dict(task.control_json or {})
            clarification_payload = dict(control_json.get("clarification_request") or {})
            clarification_payload["expires_at"] = expired_at.isoformat()
            control_json["clarification_request"] = clarification_payload
            task.control_json = control_json
            latest_turn = await session.scalar(
                select(SessionTurn)
                .where(SessionTurn.task_id == task.id)
                .where(SessionTurn.turn_type == "CLARIFY_REQUEST")
                .order_by(SessionTurn.id.desc())
                .limit(1)
                .with_for_update()
            )
            if latest_turn is None:
                raise AssertionError("Expired clarify test request turn missing")
            latest_turn.expires_at = expired_at

    async with httpx.AsyncClient(timeout=30) as client:
        answer = await client.post(
            f"{base_url}/api/v1/search/{request_id}/clarification",
            json={"selected_option_id": fallback_option_id},
        )
        if answer.status_code != 409:
            raise AssertionError(
                f"Expired clarify test expected 409 Conflict, got {answer.status_code}: {answer.text}"
            )

    final_snapshot = await poll_snapshot(base_url, request_id)
    if final_snapshot["status"] != "COMPLETED":
        raise AssertionError(f"Expired clarify test expected COMPLETED, got {final_snapshot['status']}")
    event_names = await list_event_names(request_id)
    if "clarification_default_applied" not in event_names:
        raise AssertionError("Expired clarify test expected clarification_default_applied event")
    if "clarification_received" in event_names:
        raise AssertionError("Expired clarify test should not accept a late clarification_received event")
    return {
        "request_id": request_id,
        "final_status": final_snapshot["status"],
        "default_applied": True,
    }


async def test_duplicate_clarification_submission_returns_snapshot(base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        submit = await client.post(
            f"{base_url}/api/v1/search",
            json={
                "session_id": "sess_integration_duplicate_clarify",
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
            await asyncio.sleep(1)
        if snapshot_data is None or snapshot_data["status"] != "WAITING_CLARIFICATION":
            raise AssertionError("Duplicate clarification test timed out waiting for WAITING_CLARIFICATION")

        option_id = snapshot_data["clarification_request"]["default_option_id"]
        first = await client.post(
            f"{base_url}/api/v1/search/{request_id}/clarification",
            json={"selected_option_id": option_id},
        )
        first.raise_for_status()
        second = await client.post(
            f"{base_url}/api/v1/search/{request_id}/clarification",
            json={"selected_option_id": option_id},
        )
        second.raise_for_status()
        second_snapshot = second.json()["data"]

    event_names = await list_event_names(request_id)
    if event_names.count("clarification_received") != 1:
        raise AssertionError(f"Duplicate clarification should emit one clarification_received, got {event_names}")
    return {
        "request_id": request_id,
        "duplicate_status": second_snapshot["status"],
        "clarification_received_count": event_names.count("clarification_received"),
    }


async def test_time_serialization_uses_utc(base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        submit = await client.post(
            f"{base_url}/api/v1/search",
            json={
                "session_id": "sess_integration_time_utc",
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
            await asyncio.sleep(1)
    if snapshot_data is None or snapshot_data["status"] != "WAITING_CLARIFICATION":
        raise AssertionError("UTC serialization test timed out waiting for WAITING_CLARIFICATION")
    expires_at = snapshot_data["clarification_request"]["expires_at"]
    if not expires_at.endswith("Z"):
        raise AssertionError(f"clarification expires_at should end with Z, got {expires_at}")
    events = await read_sse_until_clarify(base_url, request_id)
    if not events or not events[0]["data"]["ts"].endswith("Z"):
        raise AssertionError(f"SSE ts should end with Z, got {events}")
    return {"request_id": request_id, "expires_at": expires_at}


async def test_sse_clarification_payload_and_heartbeat(base_url: str) -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    async with httpx.AsyncClient(timeout=30) as client:
        submit = await client.post(
            f"{base_url}/api/v1/search",
            json={
                "session_id": "sess_integration_sse_clarify_payload",
                "query": "请帮我整理差旅报销规则的变化",
                "kb_code": "default",
                "scope_json": None,
            },
        )
        submit.raise_for_status()
        request_id = submit.json()["data"]["request_id"]

    events = await read_sse_until_clarify(base_url, request_id)
    clarify_event = next((item for item in events if item["event"] == "clarification_requested"), None)
    if clarify_event is None:
        raise AssertionError(f"Expected clarification_requested in SSE events, got {events}")
    if "clarification_request" not in clarify_event["data"]:
        raise AssertionError(f"SSE clarification event should carry clarification_request, got {clarify_event}")

    async with runtime.session_factory() as session:
        task = await session.scalar(select(SearchTask).where(SearchTask.request_id == request_id))
        if task is None:
            raise AssertionError("SSE clarification payload test task missing")
        last_event = await session.scalar(
            select(TaskEvent)
            .where(TaskEvent.task_id == task.id)
            .order_by(TaskEvent.id.desc())
            .limit(1)
        )
        if last_event is None:
            raise AssertionError("SSE clarification payload test expected at least one event")

    heartbeat = await read_single_sse_event(base_url, request_id, last_event_id=int(last_event.id))
    heartbeat_keys = set(heartbeat["data"].keys())
    if heartbeat["event"] != "heartbeat":
        raise AssertionError(f"Expected heartbeat after replay tail, got {heartbeat}")
    if heartbeat_keys != {"request_id", "ts"}:
        raise AssertionError(f"Heartbeat payload should only contain request_id and ts, got {heartbeat}")
    return {"request_id": request_id, "heartbeat_keys": sorted(heartbeat_keys)}


async def test_invalid_scope_validation(base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base_url}/api/v1/search",
            json={
                "session_id": "sess_bad_scope",
                "query": "请说明差旅报销规则",
                "kb_code": "default",
                "scope_json": {"document_ids": 1},
            },
        )
    if resp.status_code != 422:
        raise AssertionError(f"Invalid scope_json should return 422, got {resp.status_code}: {resp.text}")
    return {"status_code": resp.status_code}


async def test_duplicate_execution_id_is_ignored() -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    subtask_service = build_subtask_graph_service(use_task_engine=True)
    request_id = build_request_id("sess_integration_dedup", "请说明差旅报销规则")

    async with runtime.session_factory() as session:
        async with session.begin():
            await runtime.session_service.ensure_session(
                session,
                session_id="sess_integration_dedup",
                tenant_id="demo-tenant",
                user_id="demo-user",
                initial_query="请说明差旅报销规则",
            )
            task = SearchTask(
                request_id=request_id,
                session_id="sess_integration_dedup",
                tenant_id="demo-tenant",
                user_id="demo-user",
                kb_code="default",
                scope_json=None,
                original_query="请说明差旅报销规则",
                resolved_query="请说明差旅报销规则",
                task_profile_json={},
                status="PENDING",
                active_plan_version=0,
                budget_json={},
                control_json={"waiting_reason": "NONE"},
                replan_count=0,
                clarification_count=0,
                preplan_clarification_used=0,
                postexec_clarification_used=0,
                row_version=0,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(task)
            await session.flush()
            outcome = runtime.plan_service.create_plan(
                original_query=task.original_query,
                resolved_query=task.resolved_query,
                allow_clarify=False,
            )
            await runtime.run_service.activate_plan(
                session,
                task=task,
                plan_nodes=outcome.plan_nodes,
                dag_fingerprint=outcome.dag_fingerprint,
            )
            claimed = await runtime.run_service.claim_ready_batch(session, task=task, max_parallel=1)
            if not claimed:
                raise AssertionError("Idempotency test failed to claim a subtask")
            execution_id = claimed[0]["execution_id"]

    first_envelope = await subtask_service.execute(execution_id=execution_id)
    second_envelope = await subtask_service.execute(execution_id=execution_id)
    if first_envelope is None:
        raise AssertionError("First subtask execution should produce an envelope")
    if second_envelope is not None:
        raise AssertionError("Duplicate subtask execution should be ignored")

    async with runtime.session_factory() as session:
        async with session.begin():
            await runtime.run_service.apply_subtask_result(session, first_envelope)
            await runtime.evidence_service.flush_staged_payload(session, execution_id)

    async with runtime.session_factory() as session:
        task = await session.scalar(select(SearchTask).where(SearchTask.request_id == request_id))
        if task is None:
            raise AssertionError("Idempotency test task missing")
        started_events = list(
            (
                await session.scalars(
                    select(TaskEvent)
                    .where(TaskEvent.task_id == task.id)
                    .where(TaskEvent.event_type == "subtask_started")
                    .order_by(TaskEvent.id.asc())
                )
            ).all()
        )
    if len(started_events) != 1:
        raise AssertionError(f"Duplicate subtask execution should emit 1 start event, got {len(started_events)}")
    return {"execution_id": execution_id, "started_event_count": len(started_events)}


async def test_stale_result_does_not_advance_new_plan() -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    graph_service = await build_global_graph_service_from_bundle(runtime, use_task_engine=True)
    subtask_service = build_subtask_graph_service(use_task_engine=True)
    request_id = build_request_id("sess_integration_stale_resume", "请说明差旅报销规则")

    async with runtime.session_factory() as session:
        async with session.begin():
            await runtime.session_service.ensure_session(
                session,
                session_id="sess_integration_stale_resume",
                tenant_id="demo-tenant",
                user_id="demo-user",
                initial_query="请说明差旅报销规则",
            )
            task = SearchTask(
                request_id=request_id,
                session_id="sess_integration_stale_resume",
                tenant_id="demo-tenant",
                user_id="demo-user",
                kb_code="default",
                scope_json=None,
                original_query="请说明差旅报销规则",
                resolved_query="请说明差旅报销规则",
                task_profile_json={},
                status="PENDING",
                active_plan_version=0,
                budget_json={},
                control_json={"waiting_reason": "NONE"},
                replan_count=0,
                clarification_count=0,
                preplan_clarification_used=0,
                postexec_clarification_used=0,
                row_version=0,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(task)
            await session.flush()
            first_outcome = runtime.plan_service.create_plan(
                original_query=task.original_query,
                resolved_query=task.resolved_query,
                allow_clarify=False,
            )
            await runtime.run_service.activate_plan(
                session,
                task=task,
                plan_nodes=first_outcome.plan_nodes,
                dag_fingerprint=first_outcome.dag_fingerprint,
            )
            claimed = await runtime.run_service.claim_ready_batch(session, task=task, max_parallel=1)
            if not claimed:
                raise AssertionError("Stale result test failed to claim a subtask")
            execution_id = claimed[0]["execution_id"]
            task_id = task.id

    envelope = await subtask_service.execute(execution_id=execution_id)
    if envelope is None:
        raise AssertionError("Stale result test expected a subtask envelope")

    async with runtime.session_factory() as session:
        async with session.begin():
            task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id).with_for_update())
            if task is None:
                raise AssertionError("Stale result test task missing before replan")
            task.replan_count = 1
            second_outcome = runtime.plan_service.create_plan(
                original_query=task.original_query,
                resolved_query=f"{task.resolved_query}（重规划）",
                allow_clarify=False,
            )
            await runtime.run_service.activate_plan(
                session,
                task=task,
                plan_nodes=second_outcome.plan_nodes,
                dag_fingerprint=second_outcome.dag_fingerprint,
                replan_reason="test_replan",
            )

    async with runtime.session_factory() as session:
        task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
        if task is None:
            raise AssertionError("Stale result test task missing")
        before_event_names = [
            event.event_type
            for event in list(
                (
                    await session.scalars(
                        select(TaskEvent).where(TaskEvent.task_id == task.id).order_by(TaskEvent.id.asc())
                    )
                ).all()
            )
        ]

    result = await graph_service.run(
        task_id,
        entry_action="step_gate",
        result_envelope=envelope.model_dump(mode="json"),
    )

    async with runtime.session_factory() as session:
        task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
        if task is None:
            raise AssertionError("Stale result test task missing after run")
        after_events = list(
            (
                await session.scalars(
                    select(TaskEvent).where(TaskEvent.task_id == task.id).order_by(TaskEvent.id.asc())
                )
            ).all()
        )
        tail_names = [event.event_type for event in after_events[len(before_event_names):]]

    if int(task.active_plan_version or 0) != 2:
        raise AssertionError(f"Stale result should not change active plan version, got {task.active_plan_version}")
    if task.status != "EXECUTING":
        raise AssertionError(f"Stale result should leave task EXECUTING, got {task.status}")
    if tail_names != ["subtask_stale_ignored"]:
        raise AssertionError(f"Stale result should only emit subtask_stale_ignored, got {tail_names}")
    if result.get("active_plan_version") != 2:
        raise AssertionError(f"Stale result should return current state, got {result}")
    return {"task_id": task_id, "tail_events": tail_names}


async def test_maintenance_recovery_resumes_terminal_plan() -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    maintenance_service = build_maintenance_service(use_task_engine=True)
    request_id = build_request_id("sess_integration_recovery", "请说明差旅报销规则")
    stale_at = utcnow() - timedelta(minutes=5)

    async with runtime.session_factory() as session:
        async with session.begin():
            await runtime.session_service.ensure_session(
                session,
                session_id="sess_integration_recovery",
                tenant_id="demo-tenant",
                user_id="demo-user",
                initial_query="请说明差旅报销规则",
            )
            task = SearchTask(
                request_id=request_id,
                session_id="sess_integration_recovery",
                tenant_id="demo-tenant",
                user_id="demo-user",
                kb_code="default",
                scope_json=None,
                original_query="请说明差旅报销规则",
                resolved_query="请说明差旅报销规则",
                task_profile_json={},
                status="PENDING",
                active_plan_version=0,
                budget_json={},
                control_json={"waiting_reason": "NONE"},
                replan_count=0,
                clarification_count=0,
                preplan_clarification_used=0,
                postexec_clarification_used=0,
                row_version=0,
                created_at=stale_at,
                updated_at=stale_at,
            )
            session.add(task)
            await session.flush()
            outcome = runtime.plan_service.create_plan(
                original_query=task.original_query,
                resolved_query=task.resolved_query,
                allow_clarify=False,
            )
            await runtime.run_service.activate_plan(
                session,
                task=task,
                plan_nodes=outcome.plan_nodes,
                dag_fingerprint=outcome.dag_fingerprint,
            )
            subtasks = list(
                (
                    await session.scalars(
                        select(Subtask)
                        .where(Subtask.task_id == task.id)
                        .where(Subtask.plan_version == task.active_plan_version)
                    )
                ).all()
            )
            for subtask in subtasks:
                subtask.status = "COMPLETED"
                subtask.current_execution_id = None
                subtask.completed_at = stale_at
                subtask.updated_at = stale_at
            task.status = "EXECUTING"
            task.updated_at = stale_at

    summary = await maintenance_service.recover_orchestration_gaps(stall_seconds=0)
    if summary["resumed"] < 1:
        raise AssertionError(f"Maintenance recovery expected resumed >= 1, got {summary}")

    final_snapshot = None
    for _ in range(30):
        async with runtime.session_factory() as session:
            final_snapshot = await runtime.progress_service.build_snapshot(session, request_id)
        if final_snapshot.status in {"COMPLETED", "DEGRADED", "FAILED"}:
            break
        await asyncio.sleep(1)
    if final_snapshot is None or final_snapshot.status not in {"COMPLETED", "DEGRADED"}:
        raise AssertionError(f"Maintenance recovery expected terminal snapshot, got {getattr(final_snapshot, 'status', None)}")
    return {"request_id": request_id, "summary": summary, "final_status": final_snapshot.status}


async def test_maintenance_recovery_resumes_planning_and_finalizing() -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    maintenance_service = build_maintenance_service(use_task_engine=True)
    planning_request_id = build_request_id("sess_integration_recovery_planning", "请说明差旅报销规则")
    finalizing_request_id = build_request_id("sess_integration_recovery_finalizing", "请说明差旅报销规则")
    stale_at = utcnow() - timedelta(minutes=5)

    async with runtime.session_factory() as session:
        async with session.begin():
            await runtime.session_service.ensure_session(
                session,
                session_id="sess_integration_recovery_planning",
                tenant_id="demo-tenant",
                user_id="demo-user",
                initial_query="请说明差旅报销规则",
            )
            planning_task = SearchTask(
                request_id=planning_request_id,
                session_id="sess_integration_recovery_planning",
                tenant_id="demo-tenant",
                user_id="demo-user",
                kb_code="default",
                scope_json=None,
                original_query="请说明差旅报销规则",
                resolved_query="请说明差旅报销规则",
                task_profile_json={},
                status="PLANNING",
                active_plan_version=0,
                budget_json={"llm_tokens": 4000},
                control_json={"waiting_reason": "NONE"},
                replan_count=0,
                clarification_count=0,
                preplan_clarification_used=0,
                postexec_clarification_used=0,
                row_version=0,
                created_at=stale_at,
                updated_at=stale_at,
            )
            session.add(planning_task)
            await session.flush()

            await runtime.session_service.ensure_session(
                session,
                session_id="sess_integration_recovery_finalizing",
                tenant_id="demo-tenant",
                user_id="demo-user",
                initial_query="请说明差旅报销规则",
            )
            finalizing_task = SearchTask(
                request_id=finalizing_request_id,
                session_id="sess_integration_recovery_finalizing",
                tenant_id="demo-tenant",
                user_id="demo-user",
                kb_code="default",
                scope_json=None,
                original_query="请说明差旅报销规则",
                resolved_query="请说明差旅报销规则",
                task_profile_json={},
                status="PENDING",
                active_plan_version=0,
                budget_json={},
                control_json={"waiting_reason": "NONE"},
                replan_count=0,
                clarification_count=0,
                preplan_clarification_used=0,
                postexec_clarification_used=0,
                row_version=0,
                created_at=stale_at,
                updated_at=stale_at,
            )
            session.add(finalizing_task)
            await session.flush()
            outcome = runtime.plan_service.create_plan(
                original_query=finalizing_task.original_query,
                resolved_query=finalizing_task.resolved_query,
                allow_clarify=False,
            )
            await runtime.run_service.activate_plan(
                session,
                task=finalizing_task,
                plan_nodes=outcome.plan_nodes,
                dag_fingerprint=outcome.dag_fingerprint,
            )
            finalizing_subtasks = list(
                (
                    await session.scalars(
                        select(Subtask)
                        .where(Subtask.task_id == finalizing_task.id)
                        .where(Subtask.plan_version == finalizing_task.active_plan_version)
                    )
                ).all()
            )
            for subtask in finalizing_subtasks:
                subtask.status = "COMPLETED"
                subtask.current_execution_id = None
                subtask.completed_at = stale_at
                subtask.updated_at = stale_at
            finalizing_task.status = "FINALIZING"
            finalizing_task.updated_at = stale_at

    summary = await maintenance_service.recover_orchestration_gaps(stall_seconds=0)
    if summary["resumed"] < 2:
        raise AssertionError(f"Expected at least 2 resumed tasks for planning/finalizing recovery, got {summary}")

    planning_snapshot = None
    finalizing_snapshot = None
    for _ in range(30):
        async with runtime.session_factory() as session:
            planning_snapshot = await runtime.progress_service.build_snapshot(session, planning_request_id)
            finalizing_snapshot = await runtime.progress_service.build_snapshot(session, finalizing_request_id)
        if (
            planning_snapshot.status in {"COMPLETED", "DEGRADED", "FAILED", "WAITING_CLARIFICATION"}
            and finalizing_snapshot.status in {"COMPLETED", "DEGRADED", "FAILED"}
        ):
            break
        await asyncio.sleep(1)
    if planning_snapshot is None or planning_snapshot.status not in {"COMPLETED", "DEGRADED", "WAITING_CLARIFICATION"}:
        raise AssertionError(f"Planning recovery expected progress, got {getattr(planning_snapshot, 'status', None)}")
    if finalizing_snapshot is None or finalizing_snapshot.status not in {"COMPLETED", "DEGRADED"}:
        raise AssertionError(f"Finalizing recovery expected terminal snapshot, got {getattr(finalizing_snapshot, 'status', None)}")
    return {
        "summary": summary,
        "planning_status": planning_snapshot.status,
        "finalizing_status": finalizing_snapshot.status,
    }


async def test_maintenance_recovery_resumes_ready_tasks() -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    maintenance_service = build_maintenance_service(use_task_engine=True)
    request_id = build_request_id("sess_integration_recovery_ready", "请说明差旅报销规则")
    stale_at = utcnow() - timedelta(minutes=5)

    async with runtime.session_factory() as session:
        async with session.begin():
            await runtime.session_service.ensure_session(
                session,
                session_id="sess_integration_recovery_ready",
                tenant_id="demo-tenant",
                user_id="demo-user",
                initial_query="请说明差旅报销规则",
            )
            task = SearchTask(
                request_id=request_id,
                session_id="sess_integration_recovery_ready",
                tenant_id="demo-tenant",
                user_id="demo-user",
                kb_code="default",
                scope_json=None,
                original_query="请说明差旅报销规则",
                resolved_query="请说明差旅报销规则",
                task_profile_json={},
                status="PENDING",
                active_plan_version=0,
                budget_json={},
                control_json={"waiting_reason": "NONE"},
                replan_count=0,
                clarification_count=0,
                preplan_clarification_used=0,
                postexec_clarification_used=0,
                row_version=0,
                created_at=stale_at,
                updated_at=stale_at,
            )
            session.add(task)
            await session.flush()
            outcome = runtime.plan_service.create_plan(
                original_query=task.original_query,
                resolved_query=task.resolved_query,
                allow_clarify=False,
            )
            await runtime.run_service.activate_plan(
                session,
                task=task,
                plan_nodes=outcome.plan_nodes,
                dag_fingerprint=outcome.dag_fingerprint,
            )
            ready = await runtime.run_service.ensure_ready_subtasks(
                session,
                task_id=task.id,
                plan_version=task.active_plan_version,
            )
            if not ready:
                raise AssertionError("Expected READY subtasks before maintenance recovery")
            task.status = "EXECUTING"
            task.updated_at = stale_at
            for item in ready:
                item.updated_at = stale_at

    summary = await maintenance_service.recover_orchestration_gaps(stall_seconds=0)
    if summary["resumed"] < 1:
        raise AssertionError(f"Ready-task recovery expected resumed >= 1, got {summary}")

    final_snapshot = None
    for _ in range(30):
        async with runtime.session_factory() as session:
            final_snapshot = await runtime.progress_service.build_snapshot(session, request_id)
        if final_snapshot.status in {"COMPLETED", "DEGRADED", "FAILED", "WAITING_CLARIFICATION"}:
            break
        await asyncio.sleep(1)
    if final_snapshot is None or final_snapshot.status not in {"COMPLETED", "DEGRADED"}:
        raise AssertionError(f"Ready-task recovery expected terminal progress, got {getattr(final_snapshot, 'status', None)}")
    return {"request_id": request_id, "summary": summary, "final_status": final_snapshot.status}


async def test_redis_memory_layers() -> dict:
    service = build_search_command_service(use_task_engine=True)
    runtime = build_runtime_bundle(use_task_engine=True)
    accepted = await service.submit_search(
        SearchSubmitRequest(
            session_id="sess_integration_redis_layers",
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
        if final_snapshot.status in {"COMPLETED", "DEGRADED", "FAILED"}:
            break
        await asyncio.sleep(1)
    if final_snapshot is None or final_snapshot.status != "COMPLETED":
        raise AssertionError(f"Redis memory layers test expected COMPLETED, got {getattr(final_snapshot, 'status', None)}")

    async with runtime.session_factory() as session:
        task = await session.scalar(select(SearchTask).where(SearchTask.request_id == request_id))
        if task is None:
            raise AssertionError("Redis memory layers test task missing")
        run = await session.scalar(
            select(SubtaskRun)
            .where(SubtaskRun.task_id == task.id)
            .where(SubtaskRun.plan_version == task.active_plan_version)
            .where(SubtaskRun.data_plane_ref_json.is_not(None))
            .order_by(SubtaskRun.id.asc())
            .limit(1)
        )
        if run is None:
            raise AssertionError("Redis memory layers test run missing")

    await runtime.progress_service.prime_task_cache(runtime.session_factory, request_id=request_id)
    cached_snapshot = await runtime.progress_service.load_cached_snapshot(request_id)
    cached_events = await runtime.progress_service.load_cached_events_after(request_id, 0)
    working_memory = await runtime.redis_runtime.load_json("subtask_memory", run.execution_id)
    evidence_pool = await runtime.redis_runtime.load_json("evidence_pool", f"{task.request_id}:{task.active_plan_version}")
    global_state = await runtime.redis_runtime.load_json("global_state", str(task.id))

    if cached_snapshot is None:
        raise AssertionError("Expected snapshot hot cache in Redis")
    if cached_events is None or not cached_events:
        raise AssertionError("Expected event replay hot cache in Redis")
    if not working_memory:
        raise AssertionError("Expected L2 subtask working memory in Redis")
    if not evidence_pool:
        raise AssertionError("Expected L3 evidence hot pool in Redis")
    if not global_state:
        raise AssertionError("Expected control-plane global_state hot cache in Redis")
    if not (run.data_plane_ref_json or {}).get("l2_working_memory_ref"):
        raise AssertionError("Expected subtask_runs.data_plane_ref_json to reference L2 memory")
    return {
        "request_id": request_id,
        "evidence_pool_count": len(evidence_pool),
        "event_cache_count": len(cached_events),
        "working_memory_execution_id": run.execution_id,
    }


async def test_step_gate_clarify_flow(base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        submit = await client.post(
            f"{base_url}/api/v1/search",
            json={
                "session_id": "sess_integration_step_gate_clarify",
                "query": "请按你认为更合适的口径整理公司近 90 天差旅报销规则的变化",
                "kb_code": "default",
                "scope_json": None,
            },
        )
        submit.raise_for_status()
        request_id = submit.json()["data"]["request_id"]

        snapshot_data = None
        for _ in range(60):
            snapshot = await client.get(f"{base_url}/api/v1/search/{request_id}")
            snapshot.raise_for_status()
            snapshot_data = snapshot.json()["data"]
            if snapshot_data["status"] == "WAITING_CLARIFICATION":
                break
            if snapshot_data["status"] in {"COMPLETED", "DEGRADED", "FAILED"}:
                raise AssertionError(
                    f"STEP_GATE clarify test expected WAITING_CLARIFICATION, got terminal status {snapshot_data['status']}"
                )
            await asyncio.sleep(1)
        if snapshot_data is None or snapshot_data["status"] != "WAITING_CLARIFICATION":
            raise AssertionError("STEP_GATE clarify test timed out waiting for WAITING_CLARIFICATION")
        clarify_request = snapshot_data["clarification_request"]
        if clarify_request["clarification_source"] != "STEP_GATE":
            raise AssertionError(f"Expected STEP_GATE clarification, got {clarify_request}")

        answer = await client.post(
            f"{base_url}/api/v1/search/{request_id}/clarification",
            json={"selected_option_id": "opt_policy"},
        )
        answer.raise_for_status()

    final_snapshot = await poll_snapshot(base_url, request_id)
    if final_snapshot["status"] != "COMPLETED":
        raise AssertionError(f"STEP_GATE clarify expected COMPLETED, got {final_snapshot['status']}")
    if not str(final_snapshot["final_answer"] or "").startswith("回答口径：制度解释优先"):
        raise AssertionError(f"STEP_GATE clarify final answer should reflect user choice, got {final_snapshot['final_answer']}")
    event_names = await list_event_names(request_id)
    if "subtask_escalated" not in event_names:
        raise AssertionError(f"Expected subtask_escalated before STEP_GATE clarify, got {event_names}")
    return {"request_id": request_id, "final_status": final_snapshot["status"]}


async def test_dag_fingerprint_distinguishes_semantics() -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    first = runtime.plan_service.create_plan(
        original_query="请帮我整理公司近 90 天差旅报销规则的变化",
        resolved_query="请帮我整理公司近 90 天差旅报销规则的变化",
        allow_clarify=False,
    )
    second = runtime.plan_service.create_plan(
        original_query="请帮我整理公司近 30 天差旅报销规则的变化",
        resolved_query="请帮我整理公司近 30 天差旅报销规则的变化",
        allow_clarify=False,
    )
    if first.dag_fingerprint == second.dag_fingerprint:
        raise AssertionError("Semantically different plans should not share the same dag_fingerprint")
    return {
        "first": first.dag_fingerprint,
        "second": second.dag_fingerprint,
    }


async def test_final_answer_filters_invalid_citations() -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)

    class InvalidCitationLLM:
        async def generate(self, prompt, structured_schema=None, timeout_s=None):
            return {
                "text": "invalid citations",
                "structured_output": {"answer": "最终汇总如下：\n- 已生成结果", "citations": ["EC-invalid"]},
                "usage": {},
                "model": "invalid-citation-llm",
            }

    runtime.evidence_service.llm = InvalidCitationLLM()
    request_id = build_request_id("sess_integration_invalid_citations", "请说明差旅报销规则")

    async with runtime.session_factory() as session:
        async with session.begin():
            await runtime.session_service.ensure_session(
                session,
                session_id="sess_integration_invalid_citations",
                tenant_id="demo-tenant",
                user_id="demo-user",
                initial_query="请说明差旅报销规则",
            )
            task = SearchTask(
                request_id=request_id,
                session_id="sess_integration_invalid_citations",
                tenant_id="demo-tenant",
                user_id="demo-user",
                kb_code="default",
                scope_json=None,
                original_query="请说明差旅报销规则",
                resolved_query="请说明差旅报销规则",
                task_profile_json={},
                status="EXECUTING",
                active_plan_version=1,
                budget_json={},
                control_json={"waiting_reason": "NONE"},
                replan_count=0,
                clarification_count=0,
                preplan_clarification_used=0,
                postexec_clarification_used=0,
                row_version=0,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(task)
            await session.flush()
            session.add(
                Subtask(
                    tenant_id="demo-tenant",
                    task_id=task.id,
                    plan_version=1,
                    subtask_code="ST-001",
                    description="检索事实",
                    task_type="RETRIEVAL",
                    depends_on_json=[],
                    route_hints_json=["vector"],
                    acceptance_criteria_json={},
                    budget_slice_json={},
                    priority=1,
                    status="COMPLETED",
                    iteration=1,
                    max_iterations=2,
                    timeout_ms=30000,
                    current_execution_id=None,
                    final_score=0.8,
                    key_findings="ST-001: 已找到有效事实",
                    evidence_refs_json=["EC-valid"],
                    result_snapshot_json={},
                    last_error_code=None,
                    last_error_message=None,
                    row_version=0,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                    completed_at=utcnow(),
                )
            )
            session.add(
                EvidenceCard(
                    card_uid="EC-valid",
                    tenant_id="demo-tenant",
                    task_id=task.id,
                    plan_version=1,
                    produced_by_subtask="ST-001",
                    claim="高铁默认二等座",
                    claim_type="DESCRIPTIVE",
                    source_id="1:1:chunk-1",
                    source_type="VECTOR_DB",
                    source_locator_json={
                        "kb_code": "default",
                        "document_id": 1,
                        "version_id": 1,
                        "chunk_uid": "chunk-1",
                    },
                    reliability_tier="T1",
                    data_freshness=utcnow().date(),
                    retrieval_score=0.9,
                    confidence=0.8,
                    corroborated_by_json=[],
                    conflicts_with_json=[],
                    payload_json={},
                    created_at=utcnow(),
                )
            )

    async with runtime.session_factory() as session:
        result = await runtime.evidence_service.assemble_final_answer(session, task_id=task.id, plan_version=1)
    if result["citations"] != ["EC-valid"]:
        raise AssertionError(f"Invalid citations should be filtered to evidence-backed refs, got {result}")
    return {"citations": result["citations"]}


async def test_fallback_returns_partial_results() -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    graph_service = await build_global_graph_service_from_bundle(runtime, use_task_engine=True)
    subtask_service = build_subtask_graph_service(use_task_engine=True)
    request_id = build_request_id("sess_integration_fallback_partial", "请帮我整理公司近 90 天差旅报销规则的变化")

    async with runtime.session_factory() as session:
        async with session.begin():
            await runtime.session_service.ensure_session(
                session,
                session_id="sess_integration_fallback_partial",
                tenant_id="demo-tenant",
                user_id="demo-user",
                initial_query="请帮我整理公司近 90 天差旅报销规则的变化",
            )
            task = SearchTask(
                request_id=request_id,
                session_id="sess_integration_fallback_partial",
                tenant_id="demo-tenant",
                user_id="demo-user",
                kb_code="default",
                scope_json=None,
                original_query="请帮我整理公司近 90 天差旅报销规则的变化",
                resolved_query="请帮我整理公司近 90 天差旅报销规则的变化",
                task_profile_json={},
                status="PENDING",
                active_plan_version=0,
                budget_json={},
                control_json={"waiting_reason": "NONE"},
                replan_count=0,
                clarification_count=0,
                preplan_clarification_used=0,
                postexec_clarification_used=0,
                row_version=0,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(task)
            await session.flush()
            outcome = runtime.plan_service.create_plan(
                original_query=task.original_query,
                resolved_query=task.resolved_query,
                allow_clarify=False,
            )
            await runtime.run_service.activate_plan(
                session,
                task=task,
                plan_nodes=outcome.plan_nodes,
                dag_fingerprint=outcome.dag_fingerprint,
            )
            claimed = await runtime.run_service.claim_ready_batch(session, task=task, max_parallel=1)
            if not claimed:
                raise AssertionError("Fallback partial results test expected one claimed subtask")
            execution_id = claimed[0]["execution_id"]
            task_id = task.id

    envelope = await subtask_service.execute(execution_id=execution_id)
    if envelope is None:
        raise AssertionError("Fallback partial results test expected subtask envelope")

    async with runtime.session_factory() as session:
        async with session.begin():
            await runtime.run_service.apply_subtask_result(session, envelope)
            await runtime.evidence_service.flush_staged_payload(session, execution_id)
            task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
            if task is None:
                raise AssertionError("Fallback partial results task missing before fallback")
            task.last_error_code = "FORCED_FALLBACK"
            task.last_error_message = "为测试降级输出而强制进入 fallback"

    await graph_service.run(task_id, entry_action="fallback")

    async with runtime.session_factory() as session:
        snapshot = await runtime.progress_service.build_snapshot(session, request_id)
    if snapshot.status != "DEGRADED":
        raise AssertionError(f"Fallback partial results should be DEGRADED, got {snapshot.status}")
    if not snapshot.final_citations:
        raise AssertionError(f"Fallback partial results should preserve citations, got {snapshot}")
    if "不确定性说明" not in str(snapshot.final_answer or ""):
        raise AssertionError(f"Fallback partial results should include uncertainty note, got {snapshot.final_answer}")
    if "ST-001" not in list((snapshot.coverage_summary or {}).get("covered", [])):
        raise AssertionError(f"Fallback partial results should keep covered subtasks, got {snapshot.coverage_summary}")
    return {"request_id": request_id, "final_citations": snapshot.final_citations}


async def test_checkpoint_does_not_mutate_redis_url_env() -> dict:
    previous = os.environ.get("REDIS_URL")
    if "REDIS_URL" in os.environ:
        del os.environ["REDIS_URL"]
    runtime = build_runtime_bundle(use_task_engine=True)
    try:
        await build_global_graph_service_from_bundle(runtime, use_task_engine=True)
        current = os.environ.get("REDIS_URL")
        if current != previous:
            raise AssertionError(f"REDIS_URL should remain unchanged, got before={previous!r}, after={current!r}")
        return {"redis_url_env": current}
    finally:
        await close_runtime_bundle(runtime)
        if previous is None:
            os.environ.pop("REDIS_URL", None)
        else:
            os.environ["REDIS_URL"] = previous


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
            "sse_invalid_last_event_id": await test_sse_invalid_last_event_id(base_url),
            "clarify_flow": await test_clarify_flow(base_url),
            "duplicate_clarification": await test_duplicate_clarification_submission_returns_snapshot(base_url),
            "expired_clarify_defaults": await test_expired_clarify_defaults(base_url),
            "time_serialization_uses_utc": await test_time_serialization_uses_utc(base_url),
            "sse_clarification_payload": await test_sse_clarification_payload_and_heartbeat(base_url),
            "invalid_scope_validation": await test_invalid_scope_validation(base_url),
            "offline_submit": await test_offline_submit(),
            "duplicate_execution_id": await test_duplicate_execution_id_is_ignored(),
            "stale_result_resume": await test_stale_result_does_not_advance_new_plan(),
            "maintenance_recovery": await test_maintenance_recovery_resumes_terminal_plan(),
            "maintenance_recovery_planning_finalizing": await test_maintenance_recovery_resumes_planning_and_finalizing(),
            "maintenance_recovery_ready_tasks": await test_maintenance_recovery_resumes_ready_tasks(),
            "redis_memory_layers": await test_redis_memory_layers(),
            "step_gate_clarify_flow": await test_step_gate_clarify_flow(base_url),
            "dag_fingerprint_semantics": await test_dag_fingerprint_distinguishes_semantics(),
            "invalid_citation_filtering": await test_final_answer_filters_invalid_citations(),
            "fallback_partial_results": await test_fallback_returns_partial_results(),
            "checkpoint_env_isolation": await test_checkpoint_does_not_mutate_redis_url_env(),
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
