"""Initialize or reset the deepsearch demo tables."""

from __future__ import annotations

import asyncio

try:
    from ...infrastructure.database import create_tables, get_engine
    from ...infrastructure.models import Base
except ImportError:
    import sys
    from pathlib import Path

    package_parent = Path(__file__).resolve().parents[3]
    if str(package_parent) not in sys.path:
        sys.path.insert(0, str(package_parent))
    from 最小可执行demo.infrastructure.database import create_tables, get_engine
    from 最小可执行demo.infrastructure.models import Base


async def reset_tables() -> None:
    await create_tables()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


def main() -> None:
    asyncio.run(reset_tables())


if __name__ == "__main__":
    main()
