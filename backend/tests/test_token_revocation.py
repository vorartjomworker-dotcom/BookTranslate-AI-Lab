from __future__ import annotations

import asyncio

import jwt
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token, hash_password
from app.models import AuditEvent, User


async def _create_user(async_session_factory, *, email: str) -> int:
    async with async_session_factory() as session:
        user = User(
            email=email,
            password_hash=hash_password("correct-password-1"),
            role="viewer",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _token_version(async_session_factory, user_id: int) -> int:
    async with async_session_factory() as session:
        result = await session.execute(select(User.token_version).where(User.id == user_id))
        return int(result.scalar_one())


async def _logout_audit(async_session_factory, user_id: int) -> AuditEvent:
    async with async_session_factory() as session:
        result = await session.execute(
            select(AuditEvent)
            .where(AuditEvent.action == "auth.logout", AuditEvent.actor_user_id == user_id)
            .order_by(AuditEvent.id.desc())
            .limit(1)
        )
        return result.scalar_one()


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _legacy_access_token_without_version(user_id: int) -> str:
    payload = decode_access_token(create_access_token(user_id, 0))
    payload.pop("ver", None)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def test_logout_revokes_all_preexisting_tokens_and_new_version_works(
    real_auth_client,
    async_session_factory,
) -> None:
    user_id = asyncio.run(_create_user(async_session_factory, email="revoke-all@example.com"))
    token_a = create_access_token(user_id, 0)
    token_b = create_access_token(user_id, 0)

    assert real_auth_client.get("/api/v1/auth/me", headers=_authorization(token_a)).status_code == 200
    assert real_auth_client.get("/api/v1/auth/me", headers=_authorization(token_b)).status_code == 200

    logout = real_auth_client.post("/api/v1/auth/logout", headers=_authorization(token_a))
    assert logout.status_code == 204
    assert logout.content == b""
    assert asyncio.run(_token_version(async_session_factory, user_id)) == 1

    rejected_a = real_auth_client.get("/api/v1/auth/me", headers=_authorization(token_a))
    rejected_b = real_auth_client.get("/api/v1/auth/me", headers=_authorization(token_b))
    assert rejected_a.status_code == rejected_b.status_code == 401
    assert rejected_a.json()["message"] == rejected_b.json()["message"] == "Invalid or expired token."

    new_token = create_access_token(user_id, 1)
    assert real_auth_client.get("/api/v1/auth/me", headers=_authorization(new_token)).status_code == 200

    audit = asyncio.run(_logout_audit(async_session_factory, user_id))
    assert audit.outcome == "success"
    assert audit.details == {"scope": "all_access_tokens", "token_version": 1}
    assert token_a not in str(audit.details)
    assert token_b not in str(audit.details)


def test_legacy_versionless_token_is_compatible_until_first_revoke(
    real_auth_client,
    async_session_factory,
) -> None:
    user_id = asyncio.run(_create_user(async_session_factory, email="legacy-token@example.com"))
    legacy_token = _legacy_access_token_without_version(user_id)

    before = real_auth_client.get("/api/v1/auth/me", headers=_authorization(legacy_token))
    assert before.status_code == 200

    logout = real_auth_client.post("/api/v1/auth/logout", headers=_authorization(legacy_token))
    assert logout.status_code == 204

    after = real_auth_client.get("/api/v1/auth/me", headers=_authorization(legacy_token))
    assert after.status_code == 401


def test_token_with_invalid_version_claim_is_rejected(real_auth_client, async_session_factory) -> None:
    user_id = asyncio.run(_create_user(async_session_factory, email="bad-version@example.com"))
    payload = decode_access_token(create_access_token(user_id, 0))
    payload["ver"] = "0"
    malformed = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    response = real_auth_client.get("/api/v1/auth/me", headers=_authorization(malformed))
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_logout_requires_valid_bearer_token(real_auth_client) -> None:
    response = real_auth_client.post("/api/v1/auth/logout")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
