"""Password hashing and JWT helpers.

Password hashing uses Argon2id (via argon2-cffi) which is the current OWASP-recommended
default for new applications: memory-hard, tunable, and does not suffer from the bcrypt
72-byte truncation footgun.

JWTs are signed with HS256 only. The signing algorithm is never taken from the token
itself; on decode we explicitly restrict `algorithms=["HS256"]` to prevent "alg confusion"
attacks (e.g. a forged token claiming `alg: none`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

from app.core.config import settings

_password_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]

_JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _create_token(*, subject: str, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.auth_secret_key, algorithm=_JWT_ALGORITHM)


def create_access_token(user_id: int) -> str:
    return _create_token(
        subject=str(user_id),
        token_type="access",
        expires_delta=timedelta(minutes=settings.auth_access_token_expires_minutes),
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token(
        subject=str(user_id),
        token_type="refresh",
        expires_delta=timedelta(days=settings.auth_refresh_token_expires_days),
    )


class TokenError(Exception):
    """Raised for any invalid, expired, or malformed token."""


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.auth_secret_key, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired token.") from exc

    if payload.get("type") != expected_type:
        raise TokenError("Unexpected token type.")
    if "sub" not in payload:
        raise TokenError("Token is missing a subject.")
    return payload
