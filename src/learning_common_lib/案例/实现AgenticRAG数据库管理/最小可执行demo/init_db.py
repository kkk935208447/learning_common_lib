"""Reset and initialize the demo schema and runtime directory."""

from __future__ import annotations

import asyncio

try:
    from .config import get_settings
    from .db import create_tables, drop_tables
except ImportError:
    from config import get_settings
    from db import create_tables, drop_tables


async def main() -> None:
    settings = get_settings()
    # demo 目录强调“可重复重跑”，因此 init_db 直接走 drop + create。
    await drop_tables()
    await create_tables()
    print("数据库与表已重置并初始化完成")
    print(f"MySQL DSN: {settings.mysql_dsn}")
    print(f"Runtime Dir: {settings.runtime_dir}")


if __name__ == "__main__":
    asyncio.run(main())
