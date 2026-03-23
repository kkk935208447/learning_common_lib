"""Prepare upstream fixtures and reset the DeepSearch control plane."""

from __future__ import annotations

import json

try:
    from .support import prepare_demo_environment, run_async
except ImportError:
    import sys
    from pathlib import Path

    package_parent = Path(__file__).resolve().parents[3]
    if str(package_parent) not in sys.path:
        sys.path.insert(0, str(package_parent))
    from 最小可执行demo.scripts.setup.support import prepare_demo_environment, run_async


def main() -> None:
    print(json.dumps(run_async(prepare_demo_environment()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
