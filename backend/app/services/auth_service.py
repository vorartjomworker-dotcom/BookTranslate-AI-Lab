from __future__ import annotations

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    decode_access_token,
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

    async def authenticate(self, *, email: str, password: str) -> User:
        normalized_email = normalize_email(email)
        user = await self.repository.get_by_normalized_email(normalized_email)
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

    async def issue_tokens(self, user: User) -> tuple[str, int]:
        return create_access_token(user.id), settings.jwt_expire_minutes * 60

    async def get_user_from_access_token(self, access_token: str) -> User:
        try:
            payload = decode_access_token(access_token)
            user_id = int(payload["sub"])
        except (TokenError, ValueError, TypeError, KeyError) as exc:
            raise AuthenticationError("Invalid or expired token.") from exc

        user = await self.repository.get_by_id(user_id)
        if user is None:
            raise AuthenticationError("Invalid or expired token.")
        if not user.is_active:
            raise AuthenticationError("This account is inactive.")
        return user
