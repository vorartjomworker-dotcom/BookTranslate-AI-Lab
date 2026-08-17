from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.audit.service import audit_hash
from app.auth.reset_password import PasswordResetRefused, reset_user_password
from app.core.security import hash_password, verify_password
from app.models import AuditEvent
from app.repositories.user_repository import UserRepository


@pytest.mark.asyncio
async def test_cli_password_reset_revokes_tokens_clears_lockout_and_audits(async_session_factory):
    async with async_session_factory() as session:
        repository = UserRepository(session)
        user = await repository.create(
            email="Recovery.User@example.com",
            password_hash=hash_password("old-password"),
            role="editor",
        )
        user.failed_login_attempts = 7
        user.locked_until = datetime(2030, 1, 1, 12, 0, 0)
        user.token_version = 4
        await session.commit()
        user_id = user.id

    async with async_session_factory() as session:
        reset = await reset_user_password(
            session,
            email="  recovery.user@example.com  ",
            password_hash=hash_password("new-password"),
        )
        assert reset.id == user_id
        assert verify_password("new-password", reset.password_hash)
        assert reset.failed_login_attempts == 0
        assert reset.locked_until is None
        assert reset.token_version == 5

    async with async_session_factory() as session:
        event = (
            await session.execute(
                select(AuditEvent).where(AuditEvent.action == "auth.password_reset")
            )
        ).scalar_one()
        assert event.outcome == "success"
        assert event.target_type == "user"
        assert event.target_id == str(user_id)
        assert event.actor_user_id is None
        assert event.subject_hash == audit_hash("email", "recovery.user@example.com")
        assert event.subject_hash != "recovery.user@example.com"
        assert event.details == {"via": "cli", "revoked_access_tokens": True}


@pytest.mark.asyncio
async def test_cli_password_reset_unknown_user_is_refused_and_audited(async_session_factory):
    async with async_session_factory() as session:
        with pytest.raises(PasswordResetRefused, match="user not found"):
            await reset_user_password(
                session,
                email="missing@example.com",
                password_hash=hash_password("new-password"),
            )

    async with async_session_factory() as session:
        event = (
            await session.execute(
                select(AuditEvent).where(AuditEvent.action == "auth.password_reset")
            )
        ).scalar_one()
        assert event.outcome == "failure"
        assert event.target_type == "user"
        assert event.target_id is None
        assert event.subject_hash == audit_hash("email", "missing@example.com")
        assert event.details == {"via": "cli", "reason": "user_not_found"}
