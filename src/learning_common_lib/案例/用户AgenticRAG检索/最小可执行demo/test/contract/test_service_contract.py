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
    from ...infrastructure.settings import get_settings
    from ..support.production_stack_suite import run_service_suite, wait_for_health
except ImportError:
    from 最小可执行demo.infrastructure.settings import get_settings
    from 最小可执行demo.test.support.production_stack_suite import run_service_suite, wait_for_health


async def main() -> dict:
    settings = get_settings()
    base_url = f"http://{settings.api_host}:{settings.api_port}"
    await wait_for_health(base_url)
    return await run_service_suite(base_url)


if __name__ == "__main__":
    print_result(asyncio.run(main()))
