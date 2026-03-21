from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

try:
    from ..support.bootstrap import demo_root, setup_test_env
except ImportError:
    from support.bootstrap import demo_root, setup_test_env

setup_test_env()


SCRIPT_ORDER = [
    "test_offline_happy_path.py",
    "test_preplan_clarify.py",
    "test_step_gate_clarify.py",
    "test_subtask_retry.py",
    "test_replan_flow.py",
    "test_stale_result_fencing.py",
    "test_dispatch_gap_recovery.py",
    "test_runtime_cache_rebuild.py",
    "test_checkpoint_degraded_recovery.py",
    "test_checkpoint_resume_recovery.py",
    "test_fallback_partial_result.py",
    "test_invalid_citation_filter.py",
]


def main() -> None:
    root = demo_root() / "test" / "offline"
    summary: dict[str, object] = {}
    prepare_root = demo_root() / "test" / "setup"
    for script_name in ("test_prepare_upstream.py", "test_prepare_control_plane.py"):
        subprocess.run(
            [sys.executable, str(prepare_root / script_name)],
            cwd=str(demo_root()),
            check=True,
            capture_output=True,
            text=True,
        )
    for script_name in SCRIPT_ORDER:
        path = root / script_name
        result = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(demo_root()),
            check=True,
            capture_output=True,
            text=True,
        )
        summary[script_name] = json.loads(result.stdout)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
