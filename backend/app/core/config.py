from pathlib import Path

from pydantic import ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "BookTranslate AI Lab"
    log_level: str = "INFO"
    metrics_enabled: bool = False
    metrics_bearer_token: str = ""
    database_url: str = "postgresql+asyncpg://booktranslate:booktranslate@postgres:5432/booktranslate"
    redis_url: str = "redis://redis:6379/0"

    upload_dir: str = "uploads"
    max_upload_size_mb: int = 25
    max_archive_uncompressed_mb: int = 100
    max_archive_entries: int = 500
    max_archive_compression_ratio: float = 100.0
    segment_target_chars: int = 2000
    segment_hard_limit_chars: int = 3000

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_base_url: str | None = None

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-20240620"

    deepl_api_key: str = ""
    deepl_use_pro: bool = False

    default_ai_provider: str = "openai"
    default_ai_model: str = "gpt-4o"

    translation_timeout: int = 30
    translation_batch_size: int = 5
    max_retries: int = 3
    translation_stream_name: str = "translation_jobs"
    translation_consumer_group: str = "translation-workers"
    translation_consumer_name: str = "translator-worker-1"
    translation_consumer_name_prefix: str = "translator-worker"
    translation_dlq_stream_name: str = "translation_jobs_dlq"
    translation_stream_block_ms: int = 5000
    translation_queue_batch_size: int = 10
    translation_queue_reclaim_idle_ms: int = 60000
    translation_worker_concurrency: int = 1
    translation_job_retry_limit: int = 3
    translation_job_timeout_seconds: int = 300
    translation_job_max_stale_ms: int = 60000

    qa_enabled: bool = True
    auto_approve_threshold: int = 95
    quality_ai_enabled: bool = False
    quality_ai_provider: str | None = None
    quality_evaluator_version: str = "1.0.0"
    quality_pass_threshold: int = 85
    quality_review_threshold: int = 60
    quality_auto_approve_threshold: int | None = None
    quality_min_score: int | None = None
    quality_failure_threshold: int | None = None
    quality_deterministic_weight: float = 0.8
    quality_ai_weight: float = 0.2

    default_source_language: str = "en"
    default_target_language: str = "ru"

    benchmark_allow_live_provider: bool = False
    benchmark_default_max_cases: int = 10
    benchmark_default_timeout_seconds: int = 30
    benchmark_default_concurrency: int = 1
    benchmark_default_max_retries: int = 2
    benchmark_default_max_budget_usd: float = 5.0
    benchmark_dataset_name: str = "technical_translation"
    benchmark_dataset_version: str = "2026.08.15"

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 15
    cors_allowed_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            raise ValueError("log_level must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL")
        return normalized

    @field_validator("metrics_bearer_token")
    @classmethod
    def normalize_metrics_bearer_token(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_metrics_security(self) -> "Settings":
        if self.metrics_enabled and len(self.metrics_bearer_token) < 32:
            raise ValueError("metrics_bearer_token must contain at least 32 characters when metrics are enabled")
        return self

    @field_validator("default_ai_provider")
    @classmethod
    def validate_default_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"openai", "anthropic", "deepl"}
        if normalized not in allowed:
            raise ValueError("default_ai_provider must be one of: openai, anthropic, deepl")
        return normalized

    @field_validator("translation_timeout")
    @classmethod
    def validate_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("translation_timeout must be greater than 0")
        return value

    @field_validator("max_retries")
    @classmethod
    def validate_max_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("max_retries must be >= 0")
        return value

    @field_validator("translation_job_retry_limit")
    @classmethod
    def validate_job_retry_limit(cls, value: int) -> int:
        if value < 0:
            raise ValueError("translation_job_retry_limit must be >= 0")
        return value

    @field_validator("translation_stream_block_ms", "translation_job_timeout_seconds", "translation_job_max_stale_ms")
    @classmethod
    def validate_positive_ints(cls, value: int, info: ValidationInfo) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0")
        return value

    @model_validator(mode="after")
    def validate_quality_thresholds(self) -> "Settings":
        explicit = set(self.model_fields_set)
        new_thresholds_explicit = {"quality_pass_threshold", "quality_review_threshold"} & explicit
        legacy_thresholds_explicit = {
            "quality_auto_approve_threshold",
            "quality_min_score",
            "quality_failure_threshold",
        } & explicit

        if new_thresholds_explicit:
            pass_threshold = self.quality_pass_threshold
            review_threshold = self.quality_review_threshold
        elif legacy_thresholds_explicit:
            pass_threshold = self.quality_auto_approve_threshold if self.quality_auto_approve_threshold is not None else self.quality_pass_threshold
            review_threshold = self.quality_min_score if self.quality_min_score is not None else self.quality_review_threshold
            self.quality_pass_threshold = pass_threshold
            self.quality_review_threshold = review_threshold
        else:
            pass_threshold = self.quality_pass_threshold
            review_threshold = self.quality_review_threshold

        if not (0 <= review_threshold < pass_threshold <= 100):
            raise ValueError("quality thresholds must satisfy 0 <= quality_review_threshold < quality_pass_threshold <= 100")

        self.quality_auto_approve_threshold = pass_threshold
        self.quality_min_score = review_threshold
        self.quality_failure_threshold = max(0, review_threshold - 1)

        total = self.quality_deterministic_weight + self.quality_ai_weight
        if not (0.0 <= self.quality_deterministic_weight <= 1.0 and 0.0 <= self.quality_ai_weight <= 1.0):
            raise ValueError("quality weights must be between 0 and 1")
        if abs(total - 1.0) > 1e-9:
            raise ValueError("quality deterministic and AI weights must sum to 1")
        return self

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        secret = value.strip()
        if len(secret) < 32:
            raise ValueError("jwt_secret must contain at least 32 characters")
        return secret

    @field_validator("jwt_algorithm")
    @classmethod
    def validate_jwt_algorithm(cls, value: str) -> str:
        algorithm = value.strip().upper()
        if algorithm != "HS256":
            raise ValueError("jwt_algorithm must be HS256")
        return algorithm

    @field_validator("jwt_expire_minutes")
    @classmethod
    def validate_auth_durations(cls, value: int, info: ValidationInfo) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0")
        return value

    @property
    def upload_dir_path(self) -> Path:
        return Path(self.upload_dir)


settings = Settings()
