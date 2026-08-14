from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "BookTranslate AI Lab"
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

    qa_enabled: bool = True
    auto_approve_threshold: int = 95

    default_source_language: str = "en"
    default_target_language: str = "ru"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    @property
    def upload_dir_path(self) -> Path:
        return Path(self.upload_dir)


settings = Settings()
