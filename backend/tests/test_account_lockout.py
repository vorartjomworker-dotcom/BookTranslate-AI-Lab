from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings, settings
from app.core.security import hash_password
from app.core.time import utc_now_naive
from app.dependencies.db import get_db
from app.main import app
from app.models import AuditEvent, User


@pytest.fixture
def lockout_client(async_session_factory, monkeypatch):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    async def allow_login_attempt(**_kwargs) -> None:
        return None

    monkeypatch.setattr("app.api.v1.auth.enforce_login_rate_limit", allow_login_attempt)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


async def _create_user(async_session_factory, *, email: str, password: str) -> None:
    async with async_session_factory() as session:
        session.add(
            User(
                email=email,
                password_hash=hash_password(password),
                role="viewer",
                is_active=True,
            )
        )
        await session.commit()


async def _lockout_state(async_session_factory, email: str) -> tuple[int, object | None]:
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.normalized_email == email.lower()))
        user = result.scalar_one()
        return user.failed_login_attempts, user.locked_until


async def _set_lockout_state(async_session_factory, email: str, *, attempts: int, locked_until) -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.normalized_email == email.lower()))
        user = result.scalar_one()
        user.failed_login_attempts = attempts
        user.locked_until = locked_until
        await session.commit()


async def _latest_login_audit(async_session_factory) -> AuditEvent:
    async with async_session_factory() as session:
        result = await session.execute(
            select(AuditEvent)
            .where(AuditEvent.action == "auth.login")
            .order_by(AuditEvent.id.desc())
            .limit(1)
        )
        return result.scalar_one()


def test_lockout_settings_are_positive() -> None:
    configured = Settings(
        jwt_secret="x" * 32,
        login_lockout_threshold=10,
        login_lockout_minutes=15,
    )
    assert configured.login_lockout_threshold == 10
    assert configured.login_lockout_minutes == 15

    with pytest.raises(ValueError, match="login_lockout_threshold"):
        Settings(jwt_secret="x" * 32, login_lockout_threshold=0)
    with pytest.raises(ValueError, match="login_lockout_minutes"):
        Settings(jwt_secret="x" * 32, login_lockout_minutes=0)


def test_failed_passwords_persist_and_trigger_lockout(
    lockout_client: TestClient,
    async_session_factory,
    monkeypatch,
) -> None:
    email = "lock-me@example.com"
    password = "correct-password-1"
    asyncio.run(_create_user(async_session_factory, email=email, password=password))
    monkeypatch.setattr(settings, "login_lockout_threshold", 3)
    monkeypatch.setattr(settings, "login_lockout_minutes", 15)

    first = lockout_client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-1"})
    second = lockout_client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-2"})

    assert first.status_code == second.status_code == 401
    assert first.json()["message"] == second.json()["message"] == "Invalid email or password."
    attempts, locked_until = asyncio.run(_lockout_state(async_session_factory, email))
    assert attempts == 2
    assert locked_until is None

    third = lockout_client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-3"})
    assert third.status_code == 401
    assert third.json()["message"] == "Invalid email or password."

    attempts, locked_until = asyncio.run(_lockout_state(async_session_factory, email))
    assert attempts == 3
    assert locked_until is not None
    assert locked_until > utc_now_naive()

    audit = asyncio.run(_latest_login_audit(async_session_factory))
    assert audit.outcome == "failure"
    assert audit.details == {"http_status": 401, "reason": "account_locked"}
    assert email not in str(audit.details)


def test_locked_account_rejects_correct_password_with_generic_contract(
    lockout_client: TestClient,
    async_session_factory,
    monkeypatch,
) -> None:
    email = "still-locked@example.com"
    password = "correct-password-1"
    asyncio.run(_create_user(async_session_factory, email=email, password=password))
    monkeypatch.setattr(settings, "login_lockout_threshold", 2)
    monkeypatch.setattr(settings, "login_lockout_minutes", 15)

    ordinary_failure = lockout_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong-1"},
    )
    trigger = lockout_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong-2"},
    )
    locked_correct = lockout_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )

    assert ordinary_failure.status_code == trigger.status_code == locked_correct.status_code == 401
    assert ordinary_failure.json()["code"] == trigger.json()["code"] == locked_correct.json()["code"]
    assert ordinary_failure.json()["message"] == trigger.json()["message"] == locked_correct.json()["message"]


def test_expired_lock_allows_login_and_resets_state(
    lockout_client: TestClient,
    async_session_factory,
    monkeypatch,
) -> None:
    email = "expired-lock@example.com"
    password = "correct-password-1"
    asyncio.run(_create_user(async_session_factory, email=email, password=password))
    monkeypatch.setattr(settings, "login_lockout_threshold", 3)

    asyncio.run(
        _set_lockout_state(
            async_session_factory,
            email,
            attempts=3,
            locked_until=utc_now_naive() - timedelta(seconds=1),
        )
    )

    response = lockout_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text

    attempts, locked_until = asyncio.run(_lockout_state(async_session_factory, email))
    assert attempts == 0
    assert locked_until is None


def test_successful_login_clears_previous_failures(
    lockout_client: TestClient,
    async_session_factory,
) -> None:
    email = "reset-attempts@example.com"
    password = "correct-password-1"
    asyncio.run(_create_user(async_session_factory, email=email, password=password))
    asyncio.run(_set_lockout_state(async_session_factory, email, attempts=4, locked_until=None))

    response = lockout_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text

    attempts, locked_until = asyncio.run(_lockout_state(async_session_factory, email))
    assert attempts == 0
    assert locked_until is None


def test_unknown_account_and_locked_account_share_public_failure_contract(
    lockout_client: TestClient,
    async_session_factory,
) -> None:
    email = "known-locked@example.com"
    asyncio.run(_create_user(async_session_factory, email=email, password="correct-password-1"))
    asyncio.run(
        _set_lockout_state(
            async_session_factory,
            email,
            attempts=settings.login_lockout_threshold,
            locked_until=utc_now_naive() + timedelta(minutes=5),
        )
    )

    locked = lockout_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "anything"},
    )
    unknown = lockout_client.post(
        "/api/v1/auth/login",
        json={"email": "unknown-lock@example.com", "password": "anything"},
    )

    assert locked.status_code == unknown.status_code == 401
    assert locked.json()["code"] == unknown.json()["code"] == "unauthorized"
    assert locked.json()["message"] == unknown.json()["message"] == "Invalid email or password."
