"""Bootstrap helpers for running test scripts directly from subdirectories."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def demo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def setup_test_env(*, scenario_id: str | None = None, api_port: int | None = None) -> Path:
    root = demo_root()
    demo_parent = root.parent
    if str(demo_parent) not in sys.path:
        sys.path.insert(0, str(demo_parent))
    os.environ.setdefault("DEEPSEARCH_DEMO_CELERY_EAGER", "0")
    os.environ.setdefault("MIN_RAG_CELERY_EAGER", "1")
    if api_port is not None:
        os.environ["DEEPSEARCH_DEMO_API_PORT"] = str(api_port)
    if scenario_id:
        os.environ["DEEPSEARCH_DEMO_TEST_SCENARIO_ID"] = scenario_id
    else:
        os.environ.pop("DEEPSEARCH_DEMO_TEST_SCENARIO_ID", None)
    results_dir = root / "test" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    active_scenario_path = results_dir / "active_scenario.json"
    if scenario_id:
        active_scenario_path.write_text(
            json.dumps({"scenario_id": scenario_id}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    elif active_scenario_path.exists():
        active_scenario_path.unlink()
    return root


def print_result(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
