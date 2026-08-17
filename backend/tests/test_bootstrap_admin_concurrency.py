"""Regression coverage for finding #10: concurrent bootstrap-admin race condition.

Two independent CLI processes could each open a transaction, both observe
`active_admin_count == 0`, and both insert an admin row. The fix serializes the
critical section (active-admin re-check + insert) with a PostgreSQL
`pg_advisory_xact_lock`, acquired inside the same transaction that later commits
the insert. Real PostgreSQL only (`RUN_INTEGRATION_TESTS=1`) -- advisory-lock
transaction serialization is PostgreSQL-specific and cannot be exercised on SQLite.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.bootstrap_admin import AdminBootstrapRefused, bootstrap_admin_if_needed
from app.core.config import settings
from app.core.security import hash_password, normalize_email
from app.models import User
from app.repositories.user_repository import UserRepository

pytestmark = pytest.mark.skipif(
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
            {"email": normalize_email(email)},
        )
    await session.commit()


async def _seed_user(session: AsyncSession, *, email: str, role: str, is_active: bool = True) -> None:
    user = User(email=email, password_hash=hash_password("seed-password-1"), role=role, is_active=is_active)
    session.add(user)
    await session.commit()


@pytest.mark.asyncio
async def test_bootstrap_succeeds_with_zero_active_admins_and_existing_viewer_editor() -> None:
    engine, factory = _build_engine_and_factory()
    viewer_email = "finding10-viewer@example.com"
    editor_email = "finding10-editor@example.com"
    new_admin_email = "finding10-new-admin@example.com"
    try:
        async with factory() as setup:
            await _delete_by_normalized_email(setup, viewer_email, editor_email, new_admin_email)
            await _seed_user(setup, email=viewer_email, role="viewer")
            await _seed_user(setup, email=editor_email, role="editor")

        async with factory() as session:
            user = await bootstrap_admin_if_needed(
                session, email=new_admin_email, password_hash=hash_password("new-admin-pw-1")
            )
            assert user.role == "admin"
            assert user.is_active is True

        async with factory() as check:
            repo = UserRepository(check)
            assert await repo.count_active_admins() == 1
    finally:
        async with factory() as cleanup:
            await _delete_by_normalized_email(cleanup, viewer_email, editor_email, new_admin_email)
        await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_recovery_allowed_when_only_inactive_admin_exists() -> None:
    engine, factory = _build_engine_and_factory()
    inactive_admin_email = "finding10-inactive-admin@example.com"
    recovery_admin_email = "finding10-recovery-admin@example.com"
    try:
        async with factory() as setup:
            await _delete_by_normalized_email(setup, inactive_admin_email, recovery_admin_email)
            await _seed_user(setup, email=inactive_admin_email, role="admin", is_active=False)

        async with factory() as session:
            user = await bootstrap_admin_if_needed(
                session, email=recovery_admin_email, password_hash=hash_password("recovery-pw-1")
            )
            assert user.role == "admin"
            assert user.is_active is True

        async with factory() as check:
            repo = UserRepository(check)
            assert await repo.count_active_admins() == 1
    finally:
        async with factory() as cleanup:
            await _delete_by_normalized_email(cleanup, inactive_admin_email, recovery_admin_email)
        await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_refuses_when_active_admin_already_exists() -> None:
    engine, factory = _build_engine_and_factory()
    existing_admin_email = "finding10-existing-active-admin@example.com"
    second_admin_email = "finding10-second-admin@example.com"
    try:
        async with factory() as setup:
            await _delete_by_normalized_email(setup, existing_admin_email, second_admin_email)
            await _seed_user(setup, email=existing_admin_email, role="admin", is_active=True)

        async with factory() as session:
            with pytest.raises(AdminBootstrapRefused, match="active administrator already exists"):
                await bootstrap_admin_if_needed(
                    session, email=second_admin_email, password_hash=hash_password("second-pw-1")
                )

        async with factory() as check:
            repo = UserRepository(check)
            assert await repo.count_active_admins() == 1
            assert await repo.get_by_normalized_email(normalize_email(second_admin_email)) is None
    finally:
        async with factory() as cleanup:
            await _delete_by_normalized_email(cleanup, existing_admin_email, second_admin_email)
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_bootstrap_different_emails_only_one_creates_active_admin() -> None:
    """The main finding #10 regression: two independent PostgreSQL sessions race the
    bootstrap critical section with different emails (different emails are deliberate --
    this must prove the zero-active-admin invariant is enforced, not merely trigger the
    unrelated unique-email index from finding #9). Only one may create an active admin;
    the loser must wait for the advisory lock, see the winner's admin, and refuse cleanly
    with no IntegrityError/500/traceback, and no loser row must ever be persisted.
    """
    engine, factory = _build_engine_and_factory()
    winner_email = "finding10-concurrent-winner@example.com"
    loser_email = "finding10-concurrent-loser@example.com"
    try:
        async with factory() as setup:
            await _delete_by_normalized_email(setup, winner_email, loser_email)

        barrier = asyncio.Barrier(2)  # forces both coroutines to actually race, not run sequentially

        async def _attempt(email: str) -> tuple[str, BaseException | None]:
            async with factory() as session:
                await barrier.wait()
                try:
                    await bootstrap_admin_if_needed(session, email=email, password_hash=hash_password("concurrent-pw-1"))
                    return "created", None
                except AdminBootstrapRefused as exc:
                    return "refused", exc
                except BaseException as exc:  # pragma: no cover - proves no unhandled crash
                    return "error", exc

        results = await asyncio.gather(_attempt(winner_email), _attempt(loser_email))
        outcomes = [outcome for outcome, _ in results]

        assert outcomes.count("created") == 1, f"expected exactly one winner, got {results}"
        assert outcomes.count("refused") == 1, f"expected exactly one clean refusal, got {results}"
        assert "error" not in outcomes, f"unhandled exception during concurrent bootstrap: {results}"

        async with factory() as check:
            repo = UserRepository(check)
            assert await repo.count_active_admins() == 1

            winner_exists = await repo.get_by_normalized_email(normalize_email(winner_email)) is not None
            loser_exists = await repo.get_by_normalized_email(normalize_email(loser_email)) is not None
            # Exactly one of the two emails was actually persisted -- the loser's row must
            # never exist, proving the advisory lock (not the unrelated unique-email index)
            # is what stopped the second admin from being created.
            assert winner_exists != loser_exists
    finally:
        async with factory() as cleanup:
            await _delete_by_normalized_email(cleanup, winner_email, loser_email)
        await engine.dispose()


@pytest.mark.asyncio
async def test_advisory_lock_is_transaction_scoped_not_session_scoped() -> None:
    """After one bootstrap commits, a second sequential bootstrap on a fresh session must
    not hang waiting for a leftover lock: `pg_advisory_xact_lock` (unlike session-level
    `pg_advisory_lock`) auto-releases at commit, so the lock is available immediately."""
    engine, factory = _build_engine_and_factory()
    first_email = "finding10-txscope-first@example.com"
    second_email = "finding10-txscope-second@example.com"
    try:
        async with factory() as setup:
            await _delete_by_normalized_email(setup, first_email, second_email)

        async with factory() as first_session:
            await bootstrap_admin_if_needed(first_session, email=first_email, password_hash=hash_password("first-pw-1"))

        async def _second() -> str:
            async with factory() as second_session:
                try:
                    await bootstrap_admin_if_needed(
                        second_session, email=second_email, password_hash=hash_password("second-pw-1")
                    )
                    return "created"
                except AdminBootstrapRefused:
                    return "refused"

        # A leftover session-level lock would hang this indefinitely; the timeout proves
        # the lock was already released when the first transaction committed.
        outcome = await asyncio.wait_for(_second(), timeout=5)
        assert outcome == "refused"

        async with factory() as check:
            repo = UserRepository(check)
            assert await repo.count_active_admins() == 1
    finally:
        async with factory() as cleanup:
            await _delete_by_normalized_email(cleanup, first_email, second_email)
        await engine.dispose()
