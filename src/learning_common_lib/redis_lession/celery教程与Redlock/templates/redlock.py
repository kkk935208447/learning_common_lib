"""兼容层：历史上本项目把单 Redis 分布式锁模块命名为 redlock.py。

现在推荐使用 templates.distributed_lock；此模块继续保留，避免已有导入失效。
"""

from __future__ import annotations

try:
    from .distributed_lock import (
        async_distributed_lock,
        distributed_lock,
        with_lock,
        _demo,
    )
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.distributed_lock import (  # type: ignore[no-redef]
        async_distributed_lock,
        distributed_lock,
        with_lock,
        _demo,
    )

__all__ = [
    "distributed_lock",
    "async_distributed_lock",
    "with_lock",
]


if __name__ == "__main__":
    _demo()
