from __future__ import annotations

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.roles import ROLE_ADMIN
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    normalize_email,
    verify_password,
    TokenError,
)
from app.models import User
from app.repositories.user_repository import UserRepository


class AuthService:
    def __init__(self, session) -> None:
        self.session = session
        self.repository = UserRepository(session)

    async def bootstrap_admin(self, *, email: str, password: str, bootstrap_token: str | None) -> User:
        if not settings.auth_bootstrap_token:
            raise AuthenticationError("Bootstrap is disabled. Set AUTH_BOOTSTRAP_TOKEN to enable it.")
        if bootstrap_token != settings.auth_bootstrap_token:
            raise AuthenticationError("Invalid bootstrap token.")

        existing_count = await self.repository.count()
        if existing_count > 0:
            raise ConflictError("An administrator already exists. Bootstrap is only available on an empty user table.")

        normalized_email = normalize_email(email)
        user = await self.repository.create(
            email=normalized_email,
            password_hash=hash_password(password),
            role=ROLE_ADMIN,
        )
        await self.session.commit()
        return user

    async def authenticate(self, *, email: str, password: str) -> User:
        normalized_email = normalize_email(email)
        user = await self.repository.get_by_email(normalized_email)
        # Always run a hash comparison, even for unknown emails, so response timing does
        # not reveal whether the account exists.
        if user is None:
            hash_password(password)
            raise AuthenticationError("Invalid email or password.")
        if not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid email or password.")
        if not user.is_active:
            raise AuthenticationError("This account is inactive.")
        return user

    async def issue_tokens(self, user: User) -> tuple[str, str, int]:
        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token(user.id)
        return access_token, refresh_token, settings.auth_access_token_expires_minutes * 60

    async def refresh_access_token(self, refresh_token: str) -> tuple[str, str, int]:
        try:
            payload = decode_token(refresh_token, expected_type="refresh")
        except TokenError as exc:
            raise AuthenticationError("Invalid or expired refresh token.") from exc

        user = await self.repository.get_by_id(int(payload["sub"]))
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid or expired refresh token.")

        return await self.issue_tokens(user)

    async def get_user_from_access_token(self, access_token: str) -> User:
        try:
            payload = decode_token(access_token, expected_type="access")
        except TokenError as exc:
            raise AuthenticationError("Invalid or expired token.") from exc

        user = await self.repository.get_by_id(int(payload["sub"]))
        if user is None:
            raise AuthenticationError("Invalid or expired token.")
        if not user.is_active:
            raise AuthenticationError("This account is inactive.")
        return user
