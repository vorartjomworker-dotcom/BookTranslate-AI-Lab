from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from app.auth import bootstrap_admin
from app.core.security import create_access_token, hash_password
from app.dependencies.db import get_db
from app.main import app
from app.models import User
from app.repositories.user_repository import UserRepository


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
            password_hash=hash_password("admin-safety-password"),
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


def _auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_last_active_admin_cannot_deactivate_self(auth_client, async_session_factory) -> None:
    admin = asyncio.run(_create_user(async_session_factory, email="only-admin@example.com", role="admin"))

    response = auth_client.patch(
        f"/api/v1/admin/users/{admin.id}",
        json={"is_active": False},
        headers=_auth_header(admin),
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "conflict"
    persisted = asyncio.run(_get_user(async_session_factory, admin.id))
    assert persisted.is_active is True
    assert persisted.role == "admin"


def test_last_active_admin_cannot_demote_self(auth_client, async_session_factory) -> None:
    admin = asyncio.run(_create_user(async_session_factory, email="only-admin-2@example.com", role="admin"))

    response = auth_client.patch(
        f"/api/v1/admin/users/{admin.id}",
        json={"role": "viewer"},
        headers=_auth_header(admin),
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "conflict"
    persisted = asyncio.run(_get_user(async_session_factory, admin.id))
    assert persisted.is_active is True
    assert persisted.role == "admin"


def test_admin_can_be_demoted_when_another_active_admin_remains(auth_client, async_session_factory) -> None:
    admin_one = asyncio.run(_create_user(async_session_factory, email="admin-one@example.com", role="admin"))
    admin_two = asyncio.run(_create_user(async_session_factory, email="admin-two@example.com", role="admin"))

    response = auth_client.patch(
        f"/api/v1/admin/users/{admin_one.id}",
        json={"role": "editor"},
        headers=_auth_header(admin_one),
    )

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "editor"
    persisted_two = asyncio.run(_get_user(async_session_factory, admin_two.id))
    assert persisted_two.role == "admin"
    assert persisted_two.is_active is True


def test_bootstrap_recovers_when_users_exist_but_no_active_admin(async_session_factory, monkeypatch) -> None:
    asyncio.run(_create_user(async_session_factory, email="existing-viewer@example.com", role="viewer"))

    monkeypatch.setattr(bootstrap_admin, "async_session_factory", async_session_factory)
    monkeypatch.setattr(
        bootstrap_admin,
        "validate_email",
        lambda email: SimpleNamespace(email=email),
    )
    monkeypatch.setenv("ADMIN_EMAIL", "recovery-admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "recovery-admin-password")

    asyncio.run(bootstrap_admin.bootstrap())

    async def _counts() -> tuple[int, int]:
        async with async_session_factory() as session:
            repository = UserRepository(session)
            return await repository.count(), await repository.count_active_admins()

    total_users, active_admins = asyncio.run(_counts())
    assert total_users == 2
    assert active_admins == 1


def test_bootstrap_refuses_when_active_admin_exists(async_session_factory, monkeypatch) -> None:
    asyncio.run(_create_user(async_session_factory, email="existing-admin@example.com", role="admin"))

    monkeypatch.setattr(bootstrap_admin, "async_session_factory", async_session_factory)
    monkeypatch.setattr(
        bootstrap_admin,
        "validate_email",
        lambda email: SimpleNamespace(email=email),
    )
    monkeypatch.setenv("ADMIN_EMAIL", "another-admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "another-admin-password")

    with pytest.raises(SystemExit, match="active administrator already exists"):
        asyncio.run(bootstrap_admin.bootstrap())
