"""Lazy exports for the service layer so script mode and package mode stay lightweight."""

__all__ = [
    "CleanupService",
    "DocumentCommandService",
    "IndexPipelineService",
    "JanitorService",
    "OutboxDispatcherService",
    "ParsePipelineService",
    "UploadOutcome",
    "best_effort_dispatch_outbox",
    "execute_local_task",
]


def __getattr__(name: str):
    # 惰性导入的目的是减少脚本模式下的导入耦合，而不是做运行期“魔法封装”。
    if name == "CleanupService":
        from .cleanup import CleanupService

        return CleanupService
    if name in {"DocumentCommandService", "UploadOutcome"}:
        from .document_command import DocumentCommandService, UploadOutcome

        return {
            "DocumentCommandService": DocumentCommandService,
            "UploadOutcome": UploadOutcome,
        }[name]
    if name == "IndexPipelineService":
        from .index_pipeline import IndexPipelineService

        return IndexPipelineService
    if name == "JanitorService":
        from .janitor import JanitorService

        return JanitorService
    if name in {"OutboxDispatcherService", "best_effort_dispatch_outbox", "execute_local_task"}:
        from .outbox_dispatcher import OutboxDispatcherService, best_effort_dispatch_outbox, execute_local_task

        return {
            "OutboxDispatcherService": OutboxDispatcherService,
            "best_effort_dispatch_outbox": best_effort_dispatch_outbox,
            "execute_local_task": execute_local_task,
        }[name]
    if name == "ParsePipelineService":
        from .parse_pipeline import ParsePipelineService

        return ParsePipelineService
    raise AttributeError(name)
