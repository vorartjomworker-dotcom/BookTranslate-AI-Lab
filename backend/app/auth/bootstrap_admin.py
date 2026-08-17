from __future__ import annotations

import asyncio
import getpass
import os
from email_validator import validate_email
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.roles import ROLE_ADMIN
from app.core.security import hash_password, normalize_email, validate_password_policy
from app.db import async_session_factory
from app.models import User
from app.repositories.user_repository import UserRepository

# Fixed, arbitrary 64-bit key for `pg_advisory_xact_lock`. Serializes only the bootstrap-admin
# critical section (active-admin re-check + insert) across concurrent CLI processes/hosts; it is
# intentionally constant and independent of email/PID/hostname/time so every bootstrap invocation
# contends for the same lock.
_BOOTSTRAP_ADMIN_ADVISORY_LOCK_KEY = 4_257_281_795_436_432_217

# Bounded retries for the SERIALIZABLE fallback path is not used here; the advisory lock
# approach makes retries unnecessary because the critical section never actually conflicts
# concurrently at the row level.


class AdminBootstrapRefused(Exception):
    """Raised when bootstrap must refuse because an active administrator already exists,
    or the requested email is already taken by an existing user."""


async def bootstrap_admin_if_needed(session: AsyncSession, *, email: str, password_hash: str) -> User:
    """Create the first/recovery admin, serialized across concurrent processes.

    Must be called on an `AsyncSession` that owns the transaction it will commit (or roll
    back) itself -- do not call this against a session someone else will also commit.

    A `pg_advisory_xact_lock` is acquired first, within this same transaction, before any
    active-admin check. `pg_advisory_xact_lock` auto-releases on commit/rollback/connection
    loss, so a crash or refusal never leaves a stale lock (unlike session-level
    `pg_advisory_lock`). The active-admin count and email-collision checks are re-evaluated
    only *after* the lock is held, which closes the TOCTOU window where two concurrent
    bootstrap attempts could both observe zero active admins and both insert a row.
    """
    normalized_email = normalize_email(email)

    # Advisory locks are PostgreSQL-specific; other dialects (e.g. the in-memory SQLite
    # fixture used by fast unit tests) have no concurrent-process concern to serialize.
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _BOOTSTRAP_ADMIN_ADVISORY_LOCK_KEY})

    repository = UserRepository(session)
    if await repository.count_active_admins() > 0:
        await session.rollback()
        raise AdminBootstrapRefused("an active administrator already exists.")
    if await repository.get_by_normalized_email(normalized_email):
        await session.rollback()
        raise AdminBootstrapRefused(
            "that email already belongs to an existing user; use an unused email for recovery."
        )

    user = await repository.create(email=normalized_email, password_hash=password_hash, role=ROLE_ADMIN)
    await session.commit()
    return user


async def bootstrap() -> None:
    email = os.getenv("ADMIN_EMAIL") or input("Admin email: ")
    password = os.getenv("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    normalized_email = normalize_email(validate_email(email).email)
    try:
        validate_password_policy(password)
    except ValueError as exc:
        raise SystemExit(f"Admin bootstrap refused: {exc}") from None

    async with async_session_factory() as session:
        try:
            user = await bootstrap_admin_if_needed(
                session, email=normalized_email, password_hash=hash_password(password)
            )
        except AdminBootstrapRefused as exc:
            raise SystemExit(f"Admin bootstrap refused: {exc}") from None
    print(f"Created admin user {user.normalized_email}.")


if __name__ == "__main__":
    asyncio.run(bootstrap())
