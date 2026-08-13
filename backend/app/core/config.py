from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "BookTranslate AI Lab"
    database_url: str = "postgresql+asyncpg://booktranslate:booktranslate@postgres:5432/booktranslate"
    redis_url: str = "redis://redis:6379/0"

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


settings = Settings()
