from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.redis_security import safe_redis_endpoint


_TEST_JWT_SECRET = "test-only-jwt-secret-at-least-32-characters-long"


def test_redis_url_rejects_non_redis_transport() -> None:
    with pytest.raises(ValidationError, match="redis_url must use redis:// or rediss://"):
        Settings(
            jwt_secret=_TEST_JWT_SECRET,
            redis_url="http://cache.example:6379/0",
        )


def test_redis_tls_policy_is_opt_in_but_fail_closed_when_enabled() -> None:
    plain = Settings(
        jwt_secret=_TEST_JWT_SECRET,
        redis_url="redis://cache.example:6379/0",
        redis_tls_required=False,
    )
    assert plain.redis_tls_required is False

    secure = Settings(
        jwt_secret=_TEST_JWT_SECRET,
        redis_url="rediss://:secret@cache.example:6380/0",
        redis_tls_required=True,
    )
    assert secure.redis_url.startswith("rediss://")

    with pytest.raises(ValidationError, match="redis_url must use rediss:// when redis_tls_required is enabled"):
        Settings(
            jwt_secret=_TEST_JWT_SECRET,
            redis_url="redis://:secret@cache.example:6379/0",
            redis_tls_required=True,
        )


def test_safe_redis_endpoint_omits_credentials_database_and_query() -> None:
    raw = "rediss://service-user:super-secret@cache.example:6380/4?ssl_cert_reqs=required&token=hidden"
    safe = safe_redis_endpoint(raw)

    assert safe == "rediss://cache.example:6380"
    assert "service-user" not in safe
    assert "super-secret" not in safe
    assert "token" not in safe
    assert "hidden" not in safe
    assert "/4" not in safe


def test_safe_redis_endpoint_never_echoes_invalid_input() -> None:
    raw = "not-a-url-with-secret-value"
    safe = safe_redis_endpoint(raw)

    assert safe == "redis://<configured>"
    assert raw not in safe


@pytest.mark.asyncio
async def test_translator_worker_connection_log_redacts_redis_credentials(monkeypatch, caplog) -> None:
    from app.workers import translator_worker

    class FakeRedis:
        async def ping(self) -> bool:
            return True

        async def xgroup_create(self, *args, **kwargs) -> None:
            return None

        async def aclose(self) -> None:
            return None

    fake_redis = FakeRedis()
    raw_url = "rediss://worker-user:worker-password@cache.example:6380/0?token=worker-token"

    monkeypatch.setattr(translator_worker.settings, "redis_url", raw_url)
    monkeypatch.setattr(
        translator_worker.Redis,
        "from_url",
        staticmethod(lambda *args, **kwargs: fake_redis),
    )

    worker = translator_worker.TranslatorWorker()
    with caplog.at_level(logging.INFO, logger=translator_worker.__name__):
        await worker.connect()
        await worker.disconnect()

    assert "rediss://cache.example:6380" in caplog.text
    assert "worker-user" not in caplog.text
    assert "worker-password" not in caplog.text
    assert "worker-token" not in caplog.text
