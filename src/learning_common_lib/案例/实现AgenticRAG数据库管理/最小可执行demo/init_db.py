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
    # init_db 的目标是“一次清空再重建”，适合教学 demo 的重复回放。
    settings = get_settings()
    # demo 目录强调“可重复重跑”，因此 init_db 直接走 drop + create。
    # 真实生产系统不会这样做，这里是为了让样例环境尽快回到干净初始态。
    await drop_tables()
    await create_tables()
    print("数据库与表已重置并初始化完成")
    print(f"MySQL DSN: {settings.mysql_dsn}")
    print(f"Runtime Dir: {settings.runtime_dir}")


if __name__ == "__main__":
    asyncio.run(main())
