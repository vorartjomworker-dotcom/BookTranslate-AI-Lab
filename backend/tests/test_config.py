"""Tests for configuration module."""

import pytest
from app.core.config import settings


def test_settings_load() -> None:
    """Test that settings load successfully."""
    assert settings is not None
    assert settings.app_name == "BookTranslate AI Lab"


def test_settings_database_url() -> None:
    """Test database URL is configured."""
    assert settings.database_url is not None
    assert "postgresql" in settings.database_url or "asyncpg" in settings.database_url


def test_settings_redis_url() -> None:
    """Test Redis URL is configured."""
    assert settings.redis_url is not None
    assert "redis" in settings.redis_url


def test_settings_ai_defaults() -> None:
    """Test AI provider defaults are set."""
    assert settings.default_ai_provider is not None
    assert settings.default_ai_model is not None


def test_settings_translation_params() -> None:
    """Test translation parameters are configured."""
    assert settings.translation_timeout > 0
    assert settings.translation_batch_size > 0
    assert settings.max_retries >= 0


def test_settings_qa_config() -> None:
    """Test QA configuration."""
    assert isinstance(settings.qa_enabled, bool)
    assert settings.auto_approve_threshold > 0
    assert settings.auto_approve_threshold <= 100


def test_settings_language_defaults() -> None:
    """Test default language settings."""
    assert settings.default_source_language is not None
    assert settings.default_target_language is not None


def test_settings_translation_queue_defaults() -> None:
    """Test the Redis Streams queue configuration is present."""
    assert settings.translation_stream_name
    assert settings.translation_consumer_group
    assert settings.translation_dlq_stream_name
    assert settings.translation_job_retry_limit >= 0
