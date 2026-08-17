from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.audit.service import AuditService, sanitize_audit_details
from app.models import AuditEvent


def test_sanitize_audit_details_redacts_nested_credentials_and_bounds_values() -> None:
    secret_url = "redis://user:supersecret@example.test:6379/0"
    bearer = "Bearer token-value-that-must-not-survive"
    api_key = "api_key=sk-sensitive-provider-value"

    details = sanitize_audit_details(
        {
            "endpoint": secret_url,
            "nested": {
                "authorization": bearer,
                "provider_error": api_key,
            },
            "ordinary": "gpt-4o",
            "long": "x" * 1200,
        }
    )

    assert details is not None
    rendered = str(details)
    assert "supersecret" not in rendered
    assert "token-value-that-must-not-survive" not in rendered
    assert "sk-sensitive-provider-value" not in rendered
    assert "<redacted>" in rendered
    assert details["ordinary"] == "gpt-4o"
    assert len(details["long"]) == 1000


def test_sanitize_audit_details_redacts_values_by_sensitive_mapping_key() -> None:
    details = sanitize_audit_details(
        {
            "password": "raw-password-value",
            "access_token": "raw-access-token-value",
            "providerApiKey": "raw-provider-key-value",
            "clientSecret": "raw-client-secret-value",
            "headers": {"Authorization": "opaque-auth-value"},
            "token_version": 7,
            "tokens_used": 42,
        }
    )

    assert details is not None
    rendered = str(details)
    for secret in (
        "raw-password-value",
        "raw-access-token-value",
        "raw-provider-key-value",
        "raw-client-secret-value",
        "opaque-auth-value",
    ):
        assert secret not in rendered
    assert details["password"] == "<redacted>"
    assert details["access_token"] == "<redacted>"
    assert details["providerApiKey"] == "<redacted>"
    assert details["clientSecret"] == "<redacted>"
    assert details["headers"]["Authorization"] == "<redacted>"
    assert details["token_version"] == 7
    assert details["tokens_used"] == 42


def test_sanitize_audit_details_preserves_safe_operational_types() -> None:
    details = sanitize_audit_details(
        {
            "dry_run": True,
            "status": 202,
            "latency_ms": 12.5,
            "changed_fields": ["role", "is_active"],
            "none": None,
        }
    )

    assert details == {
        "dry_run": True,
        "status": 202,
        "latency_ms": 12.5,
        "changed_fields": ["role", "is_active"],
        "none": None,
    }


def test_audit_service_persists_only_sanitized_details(async_session_factory) -> None:
    async def _exercise() -> AuditEvent:
        async with async_session_factory() as session:
            event = await AuditService(session).record(
                action="security.audit_detail_test",
                outcome="success",
                details={
                    "model": "https://alice:db-password@example.test/model",
                    "message": "Authorization: Bearer audit-secret-token",
                    "nested": ["password=never-store-this", "safe-value"],
                    "access_token": "never-store-keyed-token",
                },
            )
            event_id = event.id
            await session.commit()

        async with async_session_factory() as session:
            return (
                await session.execute(select(AuditEvent).where(AuditEvent.id == event_id))
            ).scalar_one()

    event = asyncio.run(_exercise())
    rendered = str(event.details)
    assert "db-password" not in rendered
    assert "audit-secret-token" not in rendered
    assert "never-store-this" not in rendered
    assert "never-store-keyed-token" not in rendered
    assert "safe-value" in rendered
    assert "<redacted>" in rendered
