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
    from ..support.test_registry import OFFLINE_SCRIPT_SPECS, PREPARE_DEMO_ENV_SCRIPT
except ImportError:
    from support.bootstrap import demo_root, setup_test_env
    from support.test_registry import OFFLINE_SCRIPT_SPECS, PREPARE_DEMO_ENV_SCRIPT

setup_test_env()


def main() -> None:
    root = demo_root() / "test" / "offline"
    summary: dict[str, object] = {}
    # 离线总套件依赖外部 worker/beat。
    # 每轮开始前先 purge，避免上一轮残留消息引用已被重建的新表数据。
    subprocess.run(
        ["uv", "run", "celery", "-A", "workers.celery_app:celery_app", "purge", "-f"],
        cwd=str(demo_root()),
        check=True,
        capture_output=True,
        text=True,
    )
    # 初始化入口统一走 scripts/setup/prepare_demo_env.py，
    # run_all 和 production_stack_suite 都从同一套准备逻辑拿数据。
    subprocess.run(
        [sys.executable, str(demo_root() / PREPARE_DEMO_ENV_SCRIPT.relative_path)],
        cwd=str(demo_root()),
        check=True,
        capture_output=True,
        text=True,
    )
    for spec in OFFLINE_SCRIPT_SPECS:
        path = demo_root() / spec.relative_path
        result = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(demo_root()),
            check=True,
            capture_output=True,
            text=True,
        )
        summary[path.name] = json.loads(result.stdout)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
