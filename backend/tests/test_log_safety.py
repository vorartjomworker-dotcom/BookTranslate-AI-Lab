from __future__ import annotations

import logging

from app.core.log_safety import redact_sensitive_text


def test_redact_sensitive_text_removes_url_userinfo_and_named_credentials() -> None:
    raw = (
        "Redis redis://worker-user:redis-password@cache.example:6379/0?token=query-token "
        "database=postgresql+asyncpg://db-user:db-password@postgres.example:5432/booktranslate "
        "api_key=provider-key secret: signing-secret password='quoted-password'"
    )

    safe = redact_sensitive_text(raw)

    assert "worker-user" not in safe
    assert "redis-password" not in safe
    assert "query-token" not in safe
    assert "db-user" not in safe
    assert "db-password" not in safe
    assert "provider-key" not in safe
    assert "signing-secret" not in safe
    assert "quoted-password" not in safe
    assert "redis://<redacted>@cache.example:6379/0" in safe
    assert "postgresql+asyncpg://<redacted>@postgres.example:5432/booktranslate" in safe


def test_redact_sensitive_text_handles_multiple_at_characters_in_userinfo() -> None:
    raw = "redis://worker:pa@ss@cache.example:6379/0"

    safe = redact_sensitive_text(raw)

    assert safe == "redis://<redacted>@cache.example:6379/0"
    assert "worker" not in safe
    assert "pa@ss" not in safe


def test_redact_sensitive_text_removes_bearer_credentials() -> None:
    raw = "Authorization failed with Bearer eyJhbGciOiJIUzI1NiJ9.sensitive.signature"

    safe = redact_sensitive_text(raw)

    assert safe == "Authorization failed with Bearer <redacted>"
    assert "sensitive" not in safe


def test_process_log_factory_redacts_exception_argument(caplog) -> None:
    logger = logging.getLogger("booktranslate.test.secret-argument")
    secret = "redis-secret-must-not-appear"
    error = RuntimeError(
        f"connection failed for redis://worker:{secret}@cache.example:6379/0?token=query-secret"
    )

    with caplog.at_level(logging.WARNING, logger=logger.name):
        logger.warning("Dispatch failed: %s", error)

    assert "Dispatch failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert secret not in caplog.text
    assert "query-secret" not in caplog.text
    assert "redis://<redacted>@cache.example:6379/0" in caplog.text


def test_process_log_factory_redacts_exc_info_but_keeps_traceback(caplog) -> None:
    logger = logging.getLogger("booktranslate.test.secret-traceback")
    password = "database-password-must-not-appear"
    bearer = "bearer-token-must-not-appear"

    with caplog.at_level(logging.ERROR, logger=logger.name):
        try:
            raise RuntimeError(
                "database failed: "
                f"postgresql+asyncpg://booktranslate:{password}@postgres.example:5432/booktranslate "
                f"Authorization=Bearer {bearer}"
            )
        except RuntimeError:
            logger.exception("Persistence failure")

    assert "Persistence failure" in caplog.text
    assert "Traceback" in caplog.text
    assert password not in caplog.text
    assert bearer not in caplog.text
    assert "postgresql+asyncpg://<redacted>@postgres.example:5432/booktranslate" in caplog.text


def test_process_log_factory_redacts_values_by_sensitive_mapping_key(caplog) -> None:
    logger = logging.getLogger("booktranslate.test.structured-secret-fields")
    payload = {
        "password": "structured-password-value",
        "accessToken": "structured-access-token-value",
        "provider_api_key": "structured-provider-key-value",
        "client_secret": "structured-client-secret-value",
        "headers": {"Authorization": "opaque-authorization-value"},
        "token_version": 9,
        "tokens_used": 128,
    }

    with caplog.at_level(logging.INFO, logger=logger.name):
        logger.info("provider payload=%s", payload)

    for secret in (
        "structured-password-value",
        "structured-access-token-value",
        "structured-provider-key-value",
        "structured-client-secret-value",
        "opaque-authorization-value",
    ):
        assert secret not in caplog.text
    assert "'password': '<redacted>'" in caplog.text
    assert "'accessToken': '<redacted>'" in caplog.text
    assert "'token_version': 9" in caplog.text
    assert "'tokens_used': 128" in caplog.text


def test_process_log_factory_preserves_non_sensitive_operational_fields(caplog) -> None:
    logger = logging.getLogger("booktranslate.test.safe-fields")

    with caplog.at_level(logging.INFO, logger=logger.name):
        logger.info("job_id=%s segment_id=%s status=%s", 42, 17, "completed")

    assert "job_id=42 segment_id=17 status=completed" in caplog.text
