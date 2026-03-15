from __future__ import annotations

import asyncio

try:
    from .config import get_settings
    from .db import create_tables
except ImportError:
    from config import get_settings
    from db import create_tables


async def main() -> None:
    settings = get_settings()
    await create_tables()
    print("数据库与表初始化完成")
    print(f"MySQL DSN: {settings.mysql_dsn}")
    print(f"Runtime Dir: {settings.runtime_dir}")


if __name__ == "__main__":
    asyncio.run(main())
