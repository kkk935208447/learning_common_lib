"""Typed runtime settings for the AgenticRAG deepsearch demo."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
CASES_DIR = BASE_DIR.parent.parent
UPSTREAM_DEMO_DIR = CASES_DIR / "实现AgenticRAG数据库管理" / "最小可执行demo"


class Settings(BaseSettings):
    """Runtime settings shared by API, workers, and local demo scripts."""

    model_config = SettingsConfigDict(
        env_prefix="DEEPSEARCH_DEMO_",
        case_sensitive=False,
        extra="ignore",
    )

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "123456"
    mysql_database: str = "agentic_rag_min_demo"

    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = "123456"
    redis_broker_db: int = 3
    redis_backend_db: int = 4
    redis_lock_db: int = 5
    redis_cache_db: int = 6
    redis_checkpoint_db: int = 0

    runtime_dir: Path = BASE_DIR / ".runtime"
    upstream_demo_dir: Path = UPSTREAM_DEMO_DIR
    upstream_runtime_dir: Path = UPSTREAM_DEMO_DIR / ".runtime"
    test_dir: Path = BASE_DIR / "test"
    test_fixtures_dir: Path = BASE_DIR / "test" / "fixtures"
    test_results_dir: Path = BASE_DIR / "test" / "results"
    test_scenario_id: str | None = None

    table_prefix: str = "rag_search_demo"
    checkpoint_prefix: str = "rag_search_demo_cp"
    checkpoint_write_prefix: str = "rag_search_demo_cp_writes"
    cache_prefix: str = "rag_search_demo"
    runtime_cache_ttl_seconds: int = 3600
    snapshot_cache_ttl_seconds: int = 120
    event_replay_max_items: int = 256
    subtask_memory_ttl_seconds: int = 3600
    evidence_pool_ttl_seconds: int = 3600
    evidence_pool_max_items: int = 128

    celery_eager: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8092

    default_kb_code: str = "default"
    default_tenant_id: str = "demo-tenant"
    default_user_id: str = "demo-user"

    max_parallel_subtasks: int = 3
    max_replan_count: int = 2
    max_clarification_count: int = 2
    max_subtask_iterations: int = 2
    subtask_timeout_ms: int = 30_000
    clarify_timeout_seconds: int = 600

    vector_top_k: int = 8
    search_top_k: int = 8
    merged_top_k: int = 10
    final_evidence_top_k: int = 6
    embedding_dim: int = 8

    maintenance_scan_seconds: int = 10
    heartbeat_interval_seconds: int = 5
    event_poll_interval_seconds: float = 1.0
    lock_ttl_seconds: int = 60

    @computed_field
    @property
    def mysql_dsn(self) -> str:
        return (
            f"mysql+asyncmy://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    @computed_field
    @property
    def mysql_admin_dsn(self) -> str:
        return (
            f"mysql+asyncmy://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/mysql"
        )

    def redis_url(self, db: int) -> str:
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{db}"

    @computed_field
    @property
    def redis_broker_url(self) -> str:
        return self.redis_url(self.redis_broker_db)

    @computed_field
    @property
    def redis_backend_url(self) -> str:
        return self.redis_url(self.redis_backend_db)

    @computed_field
    @property
    def redis_lock_url(self) -> str:
        return self.redis_url(self.redis_lock_db)

    @computed_field
    @property
    def redis_cache_url(self) -> str:
        return self.redis_url(self.redis_cache_db)

    @computed_field
    @property
    def redis_checkpoint_url(self) -> str:
        return self.redis_url(self.redis_checkpoint_db)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    settings.test_results_dir.mkdir(parents=True, exist_ok=True)
    return settings
