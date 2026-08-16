from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.dependencies.db import get_db
from app.main import app
from app.models import User


@pytest.fixture
def auth_client(async_session_factory):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


async def _create_user(async_session_factory, *, email: str, role: str, is_active: bool = True) -> User:
    async with async_session_factory() as session:
        user = User(
            email=email,
            password_hash=hash_password("admin-update-validation-password"),
            role=role,
            is_active=is_active,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _get_user(async_session_factory, user_id: int) -> User:
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        return user


async def _set_updated_at(async_session_factory, user_id: int, value: datetime) -> None:
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.updated_at = value
        await session.commit()


def _auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_admin_patch_rejects_null_role_with_422_and_preserves_user(auth_client, async_session_factory) -> None:
    admin = asyncio.run(_create_user(async_session_factory, email="null-role-admin@example.com", role="admin"))
    target = asyncio.run(_create_user(async_session_factory, email="null-role-target@example.com", role="editor"))

    response = auth_client.patch(
        f"/api/v1/admin/users/{target.id}",
        json={"role": None},
        headers=_auth_header(admin),
    )

    assert response.status_code == 422, response.text
    persisted = asyncio.run(_get_user(async_session_factory, target.id))
    assert persisted.role == "editor"
    assert persisted.is_active is True


def test_admin_patch_rejects_null_is_active_with_422_and_preserves_user(auth_client, async_session_factory) -> None:
    admin = asyncio.run(_create_user(async_session_factory, email="null-active-admin@example.com", role="admin"))
    target = asyncio.run(_create_user(async_session_factory, email="null-active-target@example.com", role="viewer"))

    response = auth_client.patch(
        f"/api/v1/admin/users/{target.id}",
        json={"is_active": None},
        headers=_auth_header(admin),
    )

    assert response.status_code == 422, response.text
    persisted = asyncio.run(_get_user(async_session_factory, target.id))
    assert persisted.role == "viewer"
    assert persisted.is_active is True


def test_admin_patch_refreshes_user_updated_at(auth_client, async_session_factory) -> None:
    admin = asyncio.run(_create_user(async_session_factory, email="timestamp-admin@example.com", role="admin"))
    target = asyncio.run(_create_user(async_session_factory, email="timestamp-target@example.com", role="viewer"))
    old_timestamp = datetime(2000, 1, 1, 0, 0, 0)
    asyncio.run(_set_updated_at(async_session_factory, target.id, old_timestamp))

    response = auth_client.patch(
        f"/api/v1/admin/users/{target.id}",
        json={"role": "editor"},
        headers=_auth_header(admin),
    )

    assert response.status_code == 200, response.text
    persisted = asyncio.run(_get_user(async_session_factory, target.id))
    assert persisted.role == "editor"
    assert persisted.updated_at > old_timestamp
