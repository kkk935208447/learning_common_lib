from __future__ import annotations

import asyncio
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
    from ..support.production_stack_suite import test_stale_result_does_not_advance_new_plan
except ImportError:
    from 最小可执行demo.test.support.production_stack_suite import test_stale_result_does_not_advance_new_plan


if __name__ == "__main__":
    print_result(asyncio.run(test_stale_result_does_not_advance_new_plan()))
