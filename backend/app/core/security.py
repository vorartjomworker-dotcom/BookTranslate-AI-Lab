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
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

from app.core.config import settings

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 200

_password_hasher = PasswordHasher()


def validate_password_policy(password: str) -> str:
    """Validate the shared account/bootstrap password length policy."""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long.")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"Password must be at most {PASSWORD_MAX_LENGTH} characters long.")
    return password


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_access_token(user_id: int, token_version: int = 0) -> str:
    if isinstance(token_version, bool) or not isinstance(token_version, int) or token_version < 0:
        raise ValueError("token_version must be a non-negative integer")
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
        "token_type": "access",
        "ver": token_version,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class TokenError(Exception):
    """Raised for any invalid, expired, or malformed token."""


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired token.") from exc

    if payload.get("token_type") != "access" or "sub" not in payload:
        raise TokenError("Token is missing a subject.")

    # Tokens issued before migration 009 had no version claim. Treat them as version 0
    # so existing sessions survive the migration, while the first server-side revoke
    # increments the user's version and invalidates every legacy token immediately.
    version = payload.get("ver", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise TokenError("Token has an invalid version.")
    payload["ver"] = version
    return payload
