from __future__ import annotations

from typing import AsyncGenerator

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.dependencies.db import get_db
from app.main import app
from app.models import User


@pytest.fixture
def auth_client(async_session_factory, monkeypatch):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    async def allow_login_attempt(**_kwargs) -> None:
        return None

    monkeypatch.setattr("app.api.v1.auth.enforce_login_rate_limit", allow_login_attempt)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


async def _create_user(async_session_factory, *, email: str, password: str, role: str, is_active: bool = True) -> User:
    async with async_session_factory() as session:
        user = User(email=email, password_hash=hash_password(password), role=role, is_active=is_active)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assert_bearer_unauthorized(response) -> None:
    assert response.status_code == 401, response.text
    assert response.headers["WWW-Authenticate"] == "Bearer"
    body = response.json()
    assert body["code"] == "unauthorized"
    assert body["details"] == {}
    assert body["request_id"] == response.headers["X-Request-ID"]


# --- Password hashing -------------------------------------------------------------------


def test_password_hash_does_not_contain_plaintext_and_verifies_correctly() -> None:
    password = "correct horse battery staple"
    hashed = hash_password(password)

    assert password not in hashed
    assert verify_password(password, hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_password_hash_is_salted_and_unique_per_call() -> None:
    hash_one = hash_password("same-password")
    hash_two = hash_password("same-password")
    assert hash_one != hash_two


# --- Login ---------------------------------------------------------------------------


def test_login_success(auth_client, async_session_factory) -> None:
    import asyncio

    asyncio.run(_create_user(async_session_factory, email="viewer@example.com", password="viewer-pass-1", role="viewer"))
    response = auth_client.post("/api/v1/auth/login", json={"email": "viewer@example.com", "password": "viewer-pass-1"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["email"] == "viewer@example.com"
    assert body["token_type"] == "bearer"
    assert "access_token" in body and body["access_token"]
    assert "password" not in body and "password_hash" not in body["user"]


def test_login_wrong_password_returns_401(auth_client, async_session_factory) -> None:
    import asyncio

    asyncio.run(_create_user(async_session_factory, email="viewer2@example.com", password="correct-password-1", role="viewer"))
    response = auth_client.post("/api/v1/auth/login", json={"email": "viewer2@example.com", "password": "wrong-password"})
    assert response.status_code == 401
    assert "WWW-Authenticate" not in response.headers
    assert "password" not in response.text.lower().replace("invalid email or password", "")


def test_login_unknown_email_has_same_error_contract_as_wrong_password(auth_client, async_session_factory) -> None:
    import asyncio

    asyncio.run(_create_user(async_session_factory, email="known@example.com", password="correct-password-1", role="viewer"))
    known_wrong = auth_client.post("/api/v1/auth/login", json={"email": "known@example.com", "password": "nope"})
    unknown = auth_client.post("/api/v1/auth/login", json={"email": "unknown@example.com", "password": "nope"})

    assert known_wrong.status_code == unknown.status_code == 401
    assert known_wrong.json()["code"] == unknown.json()["code"]
    assert known_wrong.json()["message"] == unknown.json()["message"]


def test_login_inactive_user_returns_401(auth_client, async_session_factory) -> None:
    import asyncio

    asyncio.run(_create_user(async_session_factory, email="inactive@example.com", password="some-password-1", role="viewer", is_active=False))
    response = auth_client.post("/api/v1/auth/login", json={"email": "inactive@example.com", "password": "some-password-1"})
    assert response.status_code == 401


# --- Token validation ------------------------------------------------------------------


def test_me_without_token_returns_401(auth_client) -> None:
    response = auth_client.get("/api/v1/auth/me")
    _assert_bearer_unauthorized(response)


def test_me_with_malformed_authorization_header_returns_bearer_challenge(auth_client) -> None:
    response = auth_client.get("/api/v1/auth/me", headers={"Authorization": "NotBearer credentials"})
    _assert_bearer_unauthorized(response)


def test_me_with_invalid_token_returns_401(auth_client) -> None:
    response = auth_client.get("/api/v1/auth/me", headers=_auth_header("not-a-real-token"))
    _assert_bearer_unauthorized(response)


def test_me_with_expired_token_returns_401(auth_client, async_session_factory) -> None:
    import asyncio
    from datetime import datetime, timedelta, timezone

    user = asyncio.run(_create_user(async_session_factory, email="expired@example.com", password="some-password-1", role="viewer"))
    now = datetime.now(timezone.utc)
    expired_payload = {"sub": str(user.id), "token_type": "access", "iat": int((now - timedelta(hours=1)).timestamp()), "exp": int((now - timedelta(minutes=1)).timestamp())}
    expired_token = jwt.encode(expired_payload, settings.jwt_secret, algorithm="HS256")

    response = auth_client.get("/api/v1/auth/me", headers=_auth_header(expired_token))
    _assert_bearer_unauthorized(response)


def test_me_rejects_token_with_wrong_algorithm(auth_client, async_session_factory) -> None:
    import asyncio

    user = asyncio.run(_create_user(async_session_factory, email="algcheck@example.com", password="some-password-1", role="viewer"))
    wrong_algorithm_key = "wrong-algorithm-test-secret-0123456789abcdef0123456789abcdef0123456789abcdef"
    forged = jwt.encode({"sub": str(user.id), "token_type": "access"}, wrong_algorithm_key, algorithm="HS512")
    response = auth_client.get("/api/v1/auth/me", headers=_auth_header(forged))
    _assert_bearer_unauthorized(response)


def test_me_returns_current_user(auth_client, async_session_factory) -> None:
    import asyncio

    user = asyncio.run(_create_user(async_session_factory, email="me@example.com", password="some-password-1", role="editor"))
    token = create_access_token(user.id)
    response = auth_client.get("/api/v1/auth/me", headers=_auth_header(token))
    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"
    assert response.json()["role"] == "editor"


def test_inactive_user_token_rejected(auth_client, async_session_factory) -> None:
    import asyncio

    user = asyncio.run(_create_user(async_session_factory, email="deactivated@example.com", password="some-password-1", role="viewer", is_active=False))
    token = create_access_token(user.id)
    response = auth_client.get("/api/v1/auth/me", headers=_auth_header(token))
    _assert_bearer_unauthorized(response)


# --- RBAC on real endpoints --------------------------------------------------------------


def test_viewer_can_read_books_list(auth_client, async_session_factory) -> None:
    import asyncio

    user = asyncio.run(_create_user(async_session_factory, email="viewer3@example.com", password="some-password-1", role="viewer"))
    token = create_access_token(user.id)
    response = auth_client.get("/api/v1/books", headers=_auth_header(token))
    assert response.status_code == 200


def test_viewer_cannot_create_book(auth_client, async_session_factory) -> None:
    import asyncio

    user = asyncio.run(_create_user(async_session_factory, email="viewer4@example.com", password="some-password-1", role="viewer"))
    token = create_access_token(user.id)
    response = auth_client.post(
        "/api/v1/books",
        json={"title": "T", "author": "A", "file_path": "x", "file_type": "epub"},
        headers=_auth_header(token),
    )
    assert response.status_code == 403


def test_books_endpoint_without_token_is_401(auth_client) -> None:
    response = auth_client.get("/api/v1/books")
    assert response.status_code == 401


def test_editor_can_create_and_edit_translation(auth_client, async_session_factory) -> None:
    import asyncio

    async def _seed():
        async with async_session_factory() as session:
            from app.models import Book, Chapter, Segment

            book = Book(title="Book", author="A", file_path="x", file_type="epub", language="en", status="uploaded")
            session.add(book)
            await session.flush()
            chapter = Chapter(book_id=book.id, chapter_number=1, title="Ch1", status="segmented")
            session.add(chapter)
            await session.flush()
            segment = Segment(chapter_id=chapter.id, segment_number=1, original_text="Hello", translated_text="Bonjour")
            session.add(segment)
            await session.commit()
            await session.refresh(segment)
            return segment.id

    segment_id = asyncio.run(_seed())
    editor = asyncio.run(_create_user(async_session_factory, email="editor1@example.com", password="some-password-1", role="editor"))
    token = create_access_token(editor.id)

    response = auth_client.patch(
        f"/api/v1/segments/{segment_id}/translation",
        json={"translated_text": "Updated translation"},
        headers=_auth_header(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["translated_text"] == "Updated translation"


def test_editor_cannot_delete_segment(auth_client, async_session_factory) -> None:
    import asyncio

    editor = asyncio.run(_create_user(async_session_factory, email="editor2@example.com", password="some-password-1", role="editor"))
    token = create_access_token(editor.id)
    response = auth_client.delete("/api/v1/segments/1", headers=_auth_header(token))
    assert response.status_code == 403


def test_editor_can_create_dry_run_benchmark(auth_client, async_session_factory) -> None:
    import asyncio

    editor = asyncio.run(_create_user(async_session_factory, email="editor3@example.com", password="some-password-1", role="editor"))
    token = create_access_token(editor.id)
    response = auth_client.post(
        "/api/v1/benchmark-runs",
        json={"provider": "openai", "model": "gpt-4o"},
        headers=_auth_header(token),
    )
    assert response.status_code == 202, response.text


def test_editor_cannot_create_live_benchmark(auth_client, async_session_factory) -> None:
    import asyncio

    editor = asyncio.run(_create_user(async_session_factory, email="editor-live@example.com", password="some-password-1", role="editor"))
    token = create_access_token(editor.id)
    response = auth_client.post(
        "/api/v1/benchmark-runs",
        json={"provider": "openai", "model": "gpt-4o", "dry_run": False, "confirm_live_provider": True},
        headers=_auth_header(token),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_admin_can_delete_segment(auth_client, async_session_factory) -> None:
    import asyncio

    async def _seed():
        async with async_session_factory() as session:
            from app.models import Book, Chapter, Segment

            book = Book(title="Book", author="A", file_path="x", file_type="epub", language="en", status="uploaded")
            session.add(book)
            await session.flush()
            chapter = Chapter(book_id=book.id, chapter_number=1, title="Ch1", status="segmented")
            session.add(chapter)
            await session.flush()
            segment = Segment(chapter_id=chapter.id, segment_number=1, original_text="Hello", translated_text=None)
            session.add(segment)
            await session.commit()
            await session.refresh(segment)
            return segment.id

    segment_id = asyncio.run(_seed())
    admin = asyncio.run(_create_user(async_session_factory, email="admin2@example.com", password="some-password-1", role="admin"))
    token = create_access_token(admin.id)
    response = auth_client.delete(f"/api/v1/segments/{segment_id}", headers=_auth_header(token))
    assert response.status_code == 204


# --- Secret redaction --------------------------------------------------------------------


def test_login_response_never_leaks_password_hash_or_secret(auth_client, async_session_factory) -> None:
    import asyncio

    user = asyncio.run(_create_user(async_session_factory, email="redact@example.com", password="some-password-1", role="viewer"))
    response = auth_client.post("/api/v1/auth/login", json={"email": "redact@example.com", "password": "some-password-1"})
    body_text = response.text
    assert user.password_hash not in body_text
    assert settings.jwt_secret not in body_text
    assert "password_hash" not in response.json()["user"]
