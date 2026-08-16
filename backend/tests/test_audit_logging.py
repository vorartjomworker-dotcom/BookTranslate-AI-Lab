from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.audit import audit_hash
from app.core.security import create_access_token, hash_password
from app.dependencies.db import get_db
from app.main import app
from app.models import AuditEvent, User


@pytest.fixture
def audit_client(async_session_factory, monkeypatch):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    async def allow_login_attempt(**_kwargs) -> None:
        return None

    monkeypatch.setattr("app.api.v1.auth.enforce_login_rate_limit", allow_login_attempt)
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _create_user(async_session_factory, *, email: str, password: str, role: str) -> User:
    async with async_session_factory() as session:
        user = User(email=email, password_hash=hash_password(password), role=role, is_active=True)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _events(async_session_factory, action: str | None = None) -> list[AuditEvent]:
    async with async_session_factory() as session:
        statement = select(AuditEvent).order_by(AuditEvent.id)
        if action is not None:
            statement = statement.where(AuditEvent.action == action)
        return list((await session.execute(statement)).scalars())


def _auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_audit_hash_is_stable_and_does_not_reveal_raw_value() -> None:
    value = "sensitive@example.com"
    first = audit_hash("user_email", value)
    second = audit_hash("user_email", value)

    assert first == second
    assert first is not None
    assert len(first) == 64
    assert value not in first
    assert audit_hash("different_namespace", value) != first


def test_successful_login_is_audited_without_raw_email(audit_client, async_session_factory) -> None:
    email = "audit-login@example.com"
    user = asyncio.run(_create_user(async_session_factory, email=email, password="audit-password-1", role="viewer"))

    response = audit_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "audit-password-1"},
    )

    assert response.status_code == 200, response.text
    events = asyncio.run(_events(async_session_factory, "auth.login"))
    assert len(events) == 1
    event = events[0]
    assert event.outcome == "success"
    assert event.actor_user_id == user.id
    assert event.target_type == "user"
    assert event.target_id == str(user.id)
    assert event.subject_hash is not None
    assert event.source_hash is not None
    assert event.request_id == response.headers["X-Request-ID"]
    assert email not in str(event.details)
    assert email not in event.subject_hash


def test_failed_login_is_audited_without_account_disclosure(audit_client, async_session_factory) -> None:
    email = "audit-failure@example.com"
    asyncio.run(_create_user(async_session_factory, email=email, password="correct-password-1", role="viewer"))

    response = audit_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong-password-1"},
    )

    assert response.status_code == 401
    events = asyncio.run(_events(async_session_factory, "auth.login"))
    assert len(events) == 1
    event = events[0]
    assert event.outcome == "failure"
    assert event.actor_user_id is None
    assert event.subject_hash is not None
    assert event.details == {"http_status": 401}
    assert email not in str(event.details)


def test_admin_user_creation_and_update_are_audited(audit_client, async_session_factory) -> None:
    admin = asyncio.run(_create_user(async_session_factory, email="audit-admin@example.com", password="admin-password-1", role="admin"))

    create_response = audit_client.post(
        "/api/v1/admin/users",
        headers=_auth_header(admin),
        json={"email": "created-by-admin@example.com", "password": "created-password-1", "role": "viewer"},
    )
    assert create_response.status_code == 201, create_response.text
    created_id = create_response.json()["id"]

    update_response = audit_client.patch(
        f"/api/v1/admin/users/{created_id}",
        headers=_auth_header(admin),
        json={"role": "editor"},
    )
    assert update_response.status_code == 200, update_response.text

    events = asyncio.run(_events(async_session_factory))
    create_event = next(event for event in events if event.action == "admin.user.create")
    update_event = next(event for event in events if event.action == "admin.user.update")

    assert create_event.outcome == "success"
    assert create_event.actor_user_id == admin.id
    assert create_event.target_id == str(created_id)
    assert create_event.details == {"role": "viewer"}
    assert create_event.subject_hash is not None

    assert update_event.outcome == "success"
    assert update_event.actor_user_id == admin.id
    assert update_event.target_id == str(created_id)
    assert update_event.details == {"changed_fields": ["role"]}


def test_audit_feed_is_admin_only(audit_client, async_session_factory) -> None:
    admin = asyncio.run(_create_user(async_session_factory, email="audit-feed-admin@example.com", password="admin-password-1", role="admin"))
    viewer = asyncio.run(_create_user(async_session_factory, email="audit-feed-viewer@example.com", password="viewer-password-1", role="viewer"))

    admin_response = audit_client.get("/api/v1/admin/audit-events", headers=_auth_header(admin))
    viewer_response = audit_client.get("/api/v1/admin/audit-events", headers=_auth_header(viewer))

    assert admin_response.status_code == 200, admin_response.text
    assert set(admin_response.json()) >= {"items", "total", "page", "page_size"}
    assert viewer_response.status_code == 403
