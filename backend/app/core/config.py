from pathlib import Path

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

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-opus-20240229"

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

    @property
    def upload_dir_path(self) -> Path:
        return Path(self.upload_dir)


settings = Settings()
