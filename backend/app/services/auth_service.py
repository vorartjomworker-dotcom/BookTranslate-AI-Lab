from __future__ import annotations

from datetime import timedelta

from app.core.config import settings
from app.core.exceptions import AccountLockedError, AuthenticationError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    normalize_email,
    verify_password,
    TokenError,
)
from app.core.time import utc_now_naive
from app.models import User
from app.repositories.user_repository import UserRepository


class AuthService:
    def __init__(self, session) -> None:
        self.session = session
        self.repository = UserRepository(session)

    async def authenticate(self, *, email: str, password: str) -> User:
        normalized_email = normalize_email(email)
        user = await self.repository.get_by_normalized_email(normalized_email, for_update=True)
        # Always run a password-cost operation, even for unknown emails, so response timing
        # does not reveal whether the account exists.
        if user is None:
            hash_password(password)
            raise AuthenticationError("Invalid email or password.")

        password_matches = verify_password(password, user.password_hash)
        now = utc_now_naive()

        if user.locked_until is not None:
            if user.locked_until > now:
                # Password verification has already run. Keep the public error identical to
                # ordinary invalid credentials so lock state does not disclose account data.
                raise AccountLockedError()
            user.locked_until = None
            user.failed_login_attempts = 0

        if not password_matches:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.login_lockout_threshold:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                raise AccountLockedError()
            raise AuthenticationError("Invalid email or password.")

        if not user.is_active:
            raise AuthenticationError("This account is inactive.")

        # A successful login clears any previous failed-attempt history atomically with
        # the login audit event committed by the route.
        user.failed_login_attempts = 0
        user.locked_until = None
        return user

    async def issue_tokens(self, user: User) -> tuple[str, int]:
        return create_access_token(user.id, user.token_version), settings.jwt_expire_minutes * 60

    async def revoke_all_access_tokens(self, user_id: int) -> int:
        new_version = await self.repository.bump_token_version(user_id)
        if new_version is None:
            raise AuthenticationError("Invalid or expired token.")
        return new_version

    async def get_user_from_access_token(self, access_token: str) -> User:
        try:
            payload = decode_access_token(access_token)
            user_id = int(payload["sub"])
            token_version = payload["ver"]
        except (TokenError, ValueError, TypeError, KeyError) as exc:
            raise AuthenticationError("Invalid or expired token.") from exc

        user = await self.repository.get_by_id(user_id)
        if user is None:
            raise AuthenticationError("Invalid or expired token.")
        if token_version != user.token_version:
            raise AuthenticationError("Invalid or expired token.")
        if not user.is_active:
            raise AuthenticationError("This account is inactive.")
        return user
