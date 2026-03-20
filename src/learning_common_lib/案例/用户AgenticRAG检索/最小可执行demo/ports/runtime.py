"""Compatibility wrapper around the current runtime ports."""

from __future__ import annotations

try:
    from .checkpoint_port import CheckpointPort as BaseCheckpointProvider
    from .session_store_port import SessionStorePort as BaseSessionStorePort
    from .task_queue_port import TaskQueuePort as BaseTaskQueue
except ImportError:
    from 最小可执行demo.ports.checkpoint_port import CheckpointPort as BaseCheckpointProvider
    from 最小可执行demo.ports.session_store_port import SessionStorePort as BaseSessionStorePort
    from 最小可执行demo.ports.task_queue_port import TaskQueuePort as BaseTaskQueue

__all__ = ["BaseCheckpointProvider", "BaseSessionStorePort", "BaseTaskQueue"]
