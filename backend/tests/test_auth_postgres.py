from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.security import hash_password

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
async def test_users_table_exists_and_enforces_unique_email_and_role_constraint() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup(session)

            await session.execute(
                text(
                    "INSERT INTO users (email, password_hash, role, is_active) "
                    "VALUES (:email, :password_hash, :role, :is_active)"
                ),
                {"email": "pg-user@example.com", "password_hash": hash_password("some-password-1"), "role": "viewer", "is_active": True},
            )
            await session.commit()

            with pytest.raises(Exception):
                await session.execute(
                    text(
                        "INSERT INTO users (email, password_hash, role, is_active) "
                        "VALUES (:email, :password_hash, :role, :is_active)"
                    ),
                    {"email": "pg-user@example.com", "password_hash": "x", "role": "viewer", "is_active": True},
                )
                await session.commit()
            await session.rollback()

            with pytest.raises(Exception):
                await session.execute(
                    text(
                        "INSERT INTO users (email, password_hash, role, is_active) "
                        "VALUES (:email, :password_hash, :role, :is_active)"
                    ),
                    {"email": "pg-user-2@example.com", "password_hash": "x", "role": "not-a-role", "is_active": True},
                )
                await session.commit()
            await session.rollback()

            await _cleanup(session)
    finally:
        await engine.dispose()
