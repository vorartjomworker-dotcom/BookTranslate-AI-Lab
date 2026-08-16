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

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
        "token_type": "access",
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
    return payload
