from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import User


async def _create_user(async_session_factory, *, email: str, role: str, is_active: bool = True) -> User:
    async with async_session_factory() as session:
        user = User(
            email=email,
            normalized_email=email.lower(),
            password_hash="test-only-not-used-for-token-auth",
            role=role,
            is_active=is_active,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


def _bearer(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def test_real_auth_fixture_does_not_override_get_current_user(real_auth_client: TestClient) -> None:
    assert get_current_user not in app.dependency_overrides
    response = real_auth_client.get("/api/v1/books")
    assert response.status_code == 401


def test_real_auth_rejects_invalid_token(real_auth_client: TestClient) -> None:
    assert get_current_user not in app.dependency_overrides
    response = real_auth_client.get(
        "/api/v1/books",
        headers={"Authorization": "Bearer not-a-valid-jwt"},
    )
    assert response.status_code == 401


def test_real_jwt_viewer_is_loaded_from_database_and_is_read_only(real_auth_client: TestClient, async_session_factory) -> None:
    viewer = asyncio.run(_create_user(async_session_factory, email="real-viewer@example.com", role="viewer"))
    headers = _bearer(viewer.id)

    me = real_auth_client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["email"] == viewer.email
    assert me.json()["role"] == "viewer"

    read_response = real_auth_client.get("/api/v1/books", headers=headers)
    assert read_response.status_code == 200, read_response.text

    write_response = real_auth_client.post(
        "/api/v1/books",
        headers=headers,
        json={"title": "Forbidden", "author": "Test", "file_path": "forbidden.epub", "file_type": "epub"},
    )
    assert write_response.status_code == 403


def test_real_jwt_editor_can_use_editor_write_endpoint(real_auth_client: TestClient, async_session_factory) -> None:
    editor = asyncio.run(_create_user(async_session_factory, email="real-editor@example.com", role="editor"))
    response = real_auth_client.post(
        "/api/v1/books",
        headers=_bearer(editor.id),
        json={"title": "Editor Book", "author": "Test", "file_path": "editor.epub", "file_type": "epub"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["title"] == "Editor Book"


def test_real_jwt_admin_can_use_admin_endpoint(real_auth_client: TestClient, async_session_factory) -> None:
    admin = asyncio.run(_create_user(async_session_factory, email="real-admin@example.com", role="admin"))
    response = real_auth_client.get("/api/v1/admin/users", headers=_bearer(admin.id))
    assert response.status_code == 200, response.text
    assert any(item["email"] == admin.email and item["role"] == "admin" for item in response.json())


def test_real_jwt_inactive_user_is_rejected_after_database_lookup(real_auth_client: TestClient, async_session_factory) -> None:
    inactive = asyncio.run(
        _create_user(
            async_session_factory,
            email="real-inactive@example.com",
            role="editor",
            is_active=False,
        )
    )
    response = real_auth_client.get("/api/v1/books", headers=_bearer(inactive.id))
    assert response.status_code == 401
