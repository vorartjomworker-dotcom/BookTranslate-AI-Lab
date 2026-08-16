"""Regression coverage for finding #9: admin create-user TOCTOU on duplicate email.

Three layers are covered:
1. Sequential duplicate via the pre-check (fast path, runs everywhere).
2. Real PostgreSQL unique-index paths, bypassing the pre-check to prove both
   raw-email and normalized-email `IntegrityError` variants map to 409 and the
   session recovers after rollback.
3. Unrelated `IntegrityError`s (different SQLSTATE/constraint) must never be
   mistaken for a duplicate-email conflict.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1.admin import _is_duplicate_user_email_integrity_error, create_user
from app.core.config import settings
from app.core.exceptions import ConflictError
from app.core.security import create_access_token, hash_password
from app.dependencies.db import get_db
from app.main import app
from app.models import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate

_FORBIDDEN_LEAKS = ("integrityerror", "asyncpg", "constraint", "password_hash", "traceback", "sqlstate")


def _assert_no_db_details_leaked(body: dict) -> None:
    lowered = str(body).lower()
    for token in _FORBIDDEN_LEAKS:
        assert token not in lowered, f"response leaked DB internals: {token!r} in {body!r}"


def _direct_route_context() -> tuple[SimpleNamespace, SimpleNamespace]:
    """Build direct-call request/actor stubs for route-level integration tests.

    The actor intentionally has no persisted id because these tests exercise the
    duplicate constraint/session recovery path rather than authentication. This
    keeps the new audit-event FK valid while preserving the original test scope.
    """
    request = SimpleNamespace(state=SimpleNamespace(request_id="direct-route-test"))
    actor = SimpleNamespace(id=None)
    return request, actor


# ---------------------------------------------------------------------------
# Layer 1: sequential duplicate via the API (hits the pre-check, no DB needed)
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_client(async_session_factory):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


async def _create_admin(async_session_factory, *, email: str) -> User:
    async with async_session_factory() as session:
        user = User(email=email, password_hash=hash_password("race-admin-password-1"), role="admin", is_active=True)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


def _auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_sequential_duplicate_email_returns_safe_409(auth_client, async_session_factory) -> None:
    import asyncio

    admin = asyncio.run(_create_admin(async_session_factory, email="race-admin@example.com"))
    headers = _auth_header(admin)

    first = auth_client.post(
        "/api/v1/admin/users",
        json={"email": "Duplicate.User@Example.com", "password": "first-password-1", "role": "viewer"},
        headers=headers,
    )
    assert first.status_code == 201, first.text

    second = auth_client.post(
        "/api/v1/admin/users",
        json={"email": "duplicate.user@example.com", "password": "second-password-1", "role": "viewer"},
        headers=headers,
    )

    assert second.status_code == 409, second.text
    body = second.json()
    assert body["code"] == "conflict"
    assert body["details"] == {}
    assert body["request_id"] == second.headers["X-Request-ID"]
    _assert_no_db_details_leaked(body)


# ---------------------------------------------------------------------------
# Layer 2: real PostgreSQL unique-index paths, bypassing the pre-check
# ---------------------------------------------------------------------------

pytestmark_pg = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION_TESTS"),
    reason="PostgreSQL integration tests run only in CI with RUN_INTEGRATION_TESTS=1",
)


def _build_engine_and_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    database_url = os.getenv("DATABASE_URL", settings.database_url)
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _delete_by_normalized_email(session: AsyncSession, *emails: str) -> None:
    for email in emails:
        await session.execute(
            text("DELETE FROM users WHERE normalized_email = :email"),
            {"email": email.strip().lower()},
        )
    await session.commit()


async def _assert_real_db_duplicate_conflict_and_session_recovers(
    monkeypatch,
    *,
    existing_email: str,
    attempted_email: str,
    followup_email: str,
) -> None:
    engine, factory = _build_engine_and_factory()
    try:
        async with factory() as setup_session:
            await _delete_by_normalized_email(setup_session, existing_email, followup_email)
            existing = User(
                email=existing_email,
                password_hash=hash_password("existing-password-1"),
                role="viewer",
                is_active=True,
            )
            setup_session.add(existing)
            await setup_session.commit()

        # Simulate the TOCTOU race: both concurrent requests pass the SELECT
        # pre-check, leaving the database uniqueness indexes as the source of truth.
        monkeypatch.setattr(UserRepository, "get_by_normalized_email", AsyncMock(return_value=None))

        async with factory() as session:
            payload = UserCreate(email=attempted_email, password="new-password-123", role="viewer")
            request_stub, actor_stub = _direct_route_context()

            with pytest.raises(ConflictError) as exc_info:
                await create_user(payload, request=request_stub, db=session, actor=actor_stub)

            assert exc_info.value.code == "conflict"
            assert exc_info.value.http_status == 409
            assert exc_info.value.message == "A user with this email already exists."
            assert "asyncpg" not in exc_info.value.message.lower()
            assert "constraint" not in exc_info.value.message.lower()

            # Proof the rollback actually happened: the same session must still be
            # usable for a normal write, not stuck in a failed-transaction state.
            recovered = await UserRepository(session).create(
                email=followup_email,
                password_hash=hash_password("followup-password-1"),
                role="viewer",
            )
            await session.commit()
            assert recovered.email == followup_email
    finally:
        async with factory() as cleanup_session:
            await _delete_by_normalized_email(cleanup_session, existing_email, followup_email)
        await engine.dispose()


@pytestmark_pg
@pytest.mark.asyncio
async def test_duplicate_exact_email_db_constraint_returns_conflict_and_session_recovers(monkeypatch) -> None:
    # Exact raw-email duplicate may hit `ix_users_email` before the normalized index.
    await _assert_real_db_duplicate_conflict_and_session_recovers(
        monkeypatch,
        existing_email="race-db-exact@example.com",
        attempted_email="race-db-exact@example.com",
        followup_email="race-db-exact-followup@example.com",
    )


@pytestmark_pg
@pytest.mark.asyncio
async def test_duplicate_normalized_email_db_constraint_returns_conflict_and_session_recovers(monkeypatch) -> None:
    # Different raw strings avoid `ix_users_email`; normalization collides on
    # `ix_users_normalized_email`, proving that path is also mapped to 409.
    await _assert_real_db_duplicate_conflict_and_session_recovers(
        monkeypatch,
        existing_email="Race.DB.Normalized@Example.com",
        attempted_email="race.db.normalized@example.com",
        followup_email="race-db-normalized-followup@example.com",
    )


# ---------------------------------------------------------------------------
# Layer 3: unrelated IntegrityError must never be treated as duplicate email
# ---------------------------------------------------------------------------


def _integrity_error_with_driver_cause(*, sqlstate: str, constraint_name: str | None) -> IntegrityError:
    driver_error = Exception("driver error")
    driver_error.sqlstate = sqlstate  # type: ignore[attr-defined]
    driver_error.constraint_name = constraint_name  # type: ignore[attr-defined]

    adapter_error = Exception("adapter error")
    adapter_error.sqlstate = sqlstate  # type: ignore[attr-defined]
    adapter_error.__cause__ = driver_error
    return IntegrityError("statement", "params", adapter_error)


def test_helper_matches_both_user_email_unique_violations_and_nested_driver_metadata() -> None:
    normalized_email_orig = SimpleNamespace(sqlstate="23505", constraint_name="ix_users_normalized_email")
    exact_email_error = _integrity_error_with_driver_cause(sqlstate="23505", constraint_name="ix_users_email")
    other_unique_orig = SimpleNamespace(sqlstate="23505", constraint_name="some_other_unique_index")
    not_null_orig = SimpleNamespace(sqlstate="23502", constraint_name=None)
    opaque_orig = "orig"  # driver detail unavailable, e.g. a non-Postgres backend

    assert _is_duplicate_user_email_integrity_error(IntegrityError("s", "p", normalized_email_orig)) is True
    assert _is_duplicate_user_email_integrity_error(exact_email_error) is True
    assert _is_duplicate_user_email_integrity_error(IntegrityError("s", "p", other_unique_orig)) is False
    assert _is_duplicate_user_email_integrity_error(IntegrityError("s", "p", not_null_orig)) is False
    assert _is_duplicate_user_email_integrity_error(IntegrityError("s", "p", opaque_orig)) is False


@pytest.mark.asyncio
async def test_unrelated_integrity_error_is_not_masked_as_duplicate_email(monkeypatch) -> None:
    other_unique_orig = SimpleNamespace(sqlstate="23505", constraint_name="some_other_unique_index")
    db = AsyncMock()
    monkeypatch.setattr(UserRepository, "get_by_normalized_email", AsyncMock(return_value=None))
    monkeypatch.setattr(
        UserRepository,
        "create",
        AsyncMock(side_effect=IntegrityError("stmt", "params", other_unique_orig)),
    )

    payload = UserCreate(email="unrelated-conflict@example.com", password="some-password-123", role="viewer")
    request_stub, actor_stub = _direct_route_context()

    with pytest.raises(IntegrityError):
        await create_user(payload, request=request_stub, db=db, actor=actor_stub)

    db.rollback.assert_awaited_once()
