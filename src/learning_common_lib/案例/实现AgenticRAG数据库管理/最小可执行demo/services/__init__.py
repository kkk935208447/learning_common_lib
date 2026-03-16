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
