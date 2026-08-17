from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import hash_password
from app.services.auth_service import AuthService

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION_TESTS"),
    reason="PostgreSQL integration tests run only in CI with RUN_INTEGRATION_TESTS=1",
)


def build_test_session_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    database_url = os.getenv("DATABASE_URL", settings.database_url)
    engine = create_async_engine(database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


async def _cleanup(session) -> None:
    await session.execute(text("DELETE FROM users"))
    await session.commit()


@pytest.mark.asyncio
async def test_users_table_exists_and_enforces_unique_email_role_and_lockout_constraints() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup(session)

            await session.execute(
                text(
                    "INSERT INTO users (email, normalized_email, password_hash, role, is_active) "
                    "VALUES (:email, :normalized_email, :password_hash, :role, :is_active)"
                ),
                {"email": "pg-user@example.com", "normalized_email": "pg-user@example.com", "password_hash": hash_password("some-password-1"), "role": "viewer", "is_active": True},
            )
            await session.commit()

            row = (
                await session.execute(
                    text(
                        "SELECT failed_login_attempts, locked_until FROM users "
                        "WHERE normalized_email = 'pg-user@example.com'"
                    )
                )
            ).one()
            assert row.failed_login_attempts == 0
            assert row.locked_until is None

            with pytest.raises(Exception):
                await session.execute(
                    text(
                        "INSERT INTO users (email, normalized_email, password_hash, role, is_active) "
                        "VALUES (:email, :normalized_email, :password_hash, :role, :is_active)"
                    ),
                    {"email": "pg-other@example.com", "normalized_email": "pg-user@example.com", "password_hash": "x", "role": "viewer", "is_active": True},
                )
                await session.commit()
            await session.rollback()

            with pytest.raises(Exception):
                await session.execute(
                    text(
                        "INSERT INTO users (email, normalized_email, password_hash, role, is_active) "
                        "VALUES (:email, :normalized_email, :password_hash, :role, :is_active)"
                    ),
                    {"email": "pg-user-2@example.com", "normalized_email": "pg-user-2@example.com", "password_hash": "x", "role": "not-a-role", "is_active": True},
                )
                await session.commit()
            await session.rollback()

            with pytest.raises(Exception):
                await session.execute(
                    text(
                        "UPDATE users SET failed_login_attempts = -1 "
                        "WHERE normalized_email = 'pg-user@example.com'"
                    )
                )
                await session.commit()
            await session.rollback()

            await _cleanup(session)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_failed_logins_do_not_lose_lockout_increments() -> None:
    engine, session_factory = build_test_session_factory()
    email = "pg-lockout-race@example.com"
    try:
        async with session_factory() as session:
            await _cleanup(session)
            await session.execute(
                text(
                    "INSERT INTO users (email, normalized_email, password_hash, role, is_active) "
                    "VALUES (:email, :normalized_email, :password_hash, 'viewer', true)"
                ),
                {
                    "email": email,
                    "normalized_email": email,
                    "password_hash": hash_password("correct-password-1"),
                },
            )
            await session.commit()

        async def fail_once() -> None:
            async with session_factory() as session:
                service = AuthService(session)
                with pytest.raises(AuthenticationError):
                    await service.authenticate(email=email, password="wrong-password")
                await session.commit()

        await asyncio.gather(fail_once(), fail_once())

        async with session_factory() as session:
            attempts = (
                await session.execute(
                    text("SELECT failed_login_attempts FROM users WHERE normalized_email = :email"),
                    {"email": email},
                )
            ).scalar_one()
            assert attempts == 2
            await _cleanup(session)
    finally:
        await engine.dispose()
