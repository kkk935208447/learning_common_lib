from __future__ import annotations

import sys
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

try:
    from ..support.bootstrap import print_result, setup_test_env
except ImportError:
    from support.bootstrap import print_result, setup_test_env

setup_test_env()

try:
    from ..support.prepare_support import prepare_control_plane, run_async
except ImportError:
    from 最小可执行demo.test.support.prepare_support import prepare_control_plane, run_async


if __name__ == "__main__":
    print_result(run_async(prepare_control_plane()))
