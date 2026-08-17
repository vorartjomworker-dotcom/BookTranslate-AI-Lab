from __future__ import annotations

import asyncio
import getpass
import os

from email_validator import validate_email
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import AuditService, audit_hash
from app.core.security import hash_password, normalize_email, validate_password_policy
from app.db import async_session_factory
from app.models import User
from app.repositories.user_repository import UserRepository


class PasswordResetRefused(Exception):
    """Raised when a CLI password-reset request cannot be completed safely."""


async def reset_user_password(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
) -> User:
    """Reset one existing user's password and revoke all previously issued access tokens.

    The target row is locked before mutation so concurrent resets or logout/token-revocation
    operations cannot lose a token-version increment. The password change, lockout reset,
    token revocation, and durable audit event are committed atomically.
    """
    normalized_email = normalize_email(email)
    repository = UserRepository(session)
    user = await repository.get_by_normalized_email(normalized_email, for_update=True)

    if user is None:
        await AuditService(session).record(
            action="auth.password_reset",
            outcome="failure",
            target_type="user",
            subject_hash=audit_hash("email", normalized_email),
            details={"via": "cli", "reason": "user_not_found"},
        )
        await session.commit()
        raise PasswordResetRefused("user not found.")

    user.password_hash = password_hash
    user.failed_login_attempts = 0
    user.locked_until = None
    user.token_version += 1

    await AuditService(session).record(
        action="auth.password_reset",
        outcome="success",
        target_type="user",
        target_id=user.id,
        subject_hash=audit_hash("email", normalized_email),
        details={"via": "cli", "revoked_access_tokens": True},
    )
    await session.commit()
    return user


async def reset_password() -> None:
    email = os.getenv("RESET_USER_EMAIL") or input("User email: ")
    password = os.getenv("RESET_USER_PASSWORD") or getpass.getpass("New password: ")

    try:
        normalized_email = normalize_email(validate_email(email).email)
    except Exception as exc:
        raise SystemExit(f"Password reset refused: invalid email ({exc}).") from None

    try:
        validate_password_policy(password)
    except ValueError as exc:
        raise SystemExit(f"Password reset refused: {exc}") from None

    async with async_session_factory() as session:
        try:
            user = await reset_user_password(
                session,
                email=normalized_email,
                password_hash=hash_password(password),
            )
        except PasswordResetRefused as exc:
            raise SystemExit(f"Password reset refused: {exc}") from None

    print(f"Reset password for {user.normalized_email}; existing access tokens were revoked.")


if __name__ == "__main__":
    asyncio.run(reset_password())
