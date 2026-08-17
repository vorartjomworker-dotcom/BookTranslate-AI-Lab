from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.audit import audit_hash
from app.core.security import create_access_token, hash_password
from app.dependencies.db import get_db
from app.main import app
from app.models import AuditEvent, Book, Chapter, Segment, User


@pytest.fixture
def audit_client(async_session_factory, monkeypatch):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    async def allow_login_attempt(**_kwargs) -> None:
        return None

    monkeypatch.setattr("app.api.v1.auth.enforce_login_rate_limit", allow_login_attempt)
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _create_user(async_session_factory, *, email: str, password: str, role: str) -> User:
    async with async_session_factory() as session:
        user = User(email=email, password_hash=hash_password(password), role=role, is_active=True)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _events(async_session_factory, action: str | None = None) -> list[AuditEvent]:
    async with async_session_factory() as session:
        statement = select(AuditEvent).order_by(AuditEvent.id)
        if action is not None:
            statement = statement.where(AuditEvent.action == action)
        return list((await session.execute(statement)).scalars())


def _auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_audit_hash_is_stable_and_does_not_reveal_raw_value() -> None:
    value = "sensitive@example.com"
    first = audit_hash("user_email", value)
    second = audit_hash("user_email", value)

    assert first == second
    assert first is not None
    assert len(first) == 64
    assert value not in first
    assert audit_hash("different_namespace", value) != first


def test_successful_login_is_audited_without_raw_email(audit_client, async_session_factory) -> None:
    email = "audit-login@example.com"
    user = asyncio.run(_create_user(async_session_factory, email=email, password="audit-password-1", role="viewer"))

    response = audit_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "audit-password-1"},
    )

    assert response.status_code == 200, response.text
    events = asyncio.run(_events(async_session_factory, "auth.login"))
    assert len(events) == 1
    event = events[0]
    assert event.outcome == "success"
    assert event.actor_user_id == user.id
    assert event.target_type == "user"
    assert event.target_id == str(user.id)
    assert event.subject_hash is not None
    assert event.source_hash is not None
    assert event.request_id == response.headers["X-Request-ID"]
    assert email not in str(event.details)
    assert email not in event.subject_hash


def test_failed_login_is_audited_without_account_disclosure(audit_client, async_session_factory) -> None:
    email = "audit-failure@example.com"
    asyncio.run(_create_user(async_session_factory, email=email, password="correct-password-1", role="viewer"))

    response = audit_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong-password-1"},
    )

    assert response.status_code == 401
    events = asyncio.run(_events(async_session_factory, "auth.login"))
    assert len(events) == 1
    event = events[0]
    assert event.outcome == "failure"
    assert event.actor_user_id is None
    assert event.subject_hash is not None
    assert event.details == {"http_status": 401}
    assert email not in str(event.details)


def test_admin_user_creation_and_update_are_audited(audit_client, async_session_factory) -> None:
    admin = asyncio.run(_create_user(async_session_factory, email="audit-admin@example.com", password="admin-password-1", role="admin"))

    create_response = audit_client.post(
        "/api/v1/admin/users",
        headers=_auth_header(admin),
        json={"email": "created-by-admin@example.com", "password": "created-password-1", "role": "viewer"},
    )
    assert create_response.status_code == 201, create_response.text
    created_id = create_response.json()["id"]

    update_response = audit_client.patch(
        f"/api/v1/admin/users/{created_id}",
        headers=_auth_header(admin),
        json={"role": "editor"},
    )
    assert update_response.status_code == 200, update_response.text

    events = asyncio.run(_events(async_session_factory))
    create_event = next(event for event in events if event.action == "admin.user.create")
    update_event = next(event for event in events if event.action == "admin.user.update")

    assert create_event.outcome == "success"
    assert create_event.actor_user_id == admin.id
    assert create_event.target_id == str(created_id)
    assert create_event.details == {"role": "viewer"}
    assert create_event.subject_hash is not None

    assert update_event.outcome == "success"
    assert update_event.actor_user_id == admin.id
    assert update_event.target_id == str(created_id)
    assert update_event.details == {"changed_fields": ["role"]}


def test_destructive_resource_deletes_are_audited(audit_client, async_session_factory) -> None:
    admin = asyncio.run(_create_user(async_session_factory, email="audit-delete-admin@example.com", password="admin-password-1", role="admin"))

    async def _seed() -> tuple[int, int, int]:
        async with async_session_factory() as session:
            book_for_segment = Book(title="Segment Book", author="A", file_path="segment.epub", file_type="epub", language="en", status="uploaded")
            session.add(book_for_segment)
            await session.flush()
            chapter_for_segment = Chapter(book_id=book_for_segment.id, chapter_number=1, title="Segment Chapter", status="segmented")
            session.add(chapter_for_segment)
            await session.flush()
            segment = Segment(chapter_id=chapter_for_segment.id, segment_number=1, original_text="Hello", translated_text=None)
            session.add(segment)

            book_for_chapter = Book(title="Chapter Book", author="A", file_path="chapter.epub", file_type="epub", language="en", status="uploaded")
            session.add(book_for_chapter)
            await session.flush()
            chapter = Chapter(book_id=book_for_chapter.id, chapter_number=1, title="Delete Chapter", status="segmented")
            session.add(chapter)

            book = Book(title="Delete Book", author="A", file_path="book.epub", file_type="epub", language="en", status="uploaded")
            session.add(book)
            await session.commit()
            await session.refresh(segment)
            await session.refresh(chapter)
            await session.refresh(book)
            return segment.id, chapter.id, book.id

    segment_id, chapter_id, book_id = asyncio.run(_seed())
    headers = _auth_header(admin)

    segment_response = audit_client.delete(f"/api/v1/segments/{segment_id}", headers=headers)
    chapter_response = audit_client.delete(f"/api/v1/chapters/{chapter_id}", headers=headers)
    book_response = audit_client.delete(f"/api/v1/books/{book_id}", headers=headers)

    assert segment_response.status_code == 204, segment_response.text
    assert chapter_response.status_code == 204, chapter_response.text
    assert book_response.status_code == 204, book_response.text

    events = asyncio.run(_events(async_session_factory))
    by_action = {event.action: event for event in events}
    assert by_action["segment.delete"].target_id == str(segment_id)
    assert by_action["chapter.delete"].target_id == str(chapter_id)
    assert by_action["book.delete"].target_id == str(book_id)
    for action in ("segment.delete", "chapter.delete", "book.delete"):
        assert by_action[action].outcome == "success"
        assert by_action[action].actor_user_id == admin.id
        assert by_action[action].request_id is not None


def test_benchmark_create_and_cancel_are_audited(audit_client, async_session_factory) -> None:
    admin = asyncio.run(_create_user(async_session_factory, email="audit-benchmark-admin@example.com", password="admin-password-1", role="admin"))
    headers = _auth_header(admin)

    create_response = audit_client.post(
        "/api/v1/benchmark-runs",
        headers=headers,
        json={"provider": "openai", "model": "gpt-4o", "dry_run": True},
    )
    assert create_response.status_code == 202, create_response.text
    run_id = create_response.json()["run_id"]

    cancel_response = audit_client.post(
        f"/api/v1/benchmark-runs/{run_id}/cancel",
        headers=headers,
        json={"reason": "audit regression test"},
    )
    assert cancel_response.status_code == 202, cancel_response.text

    events = asyncio.run(_events(async_session_factory))
    create_event = next(event for event in events if event.action == "benchmark.create")
    cancel_event = next(event for event in events if event.action == "benchmark.cancel")

    assert create_event.actor_user_id == admin.id
    assert create_event.outcome == "success"
    assert create_event.details == {
        "provider": "openai",
        "model": "gpt-4o",
        "dry_run": True,
        "dataset_version": create_response.json()["dataset_version"],
    }
    assert cancel_event.actor_user_id == admin.id
    assert cancel_event.target_id == run_id
    assert cancel_event.details["reason_provided"] is True
    assert "audit regression test" not in str(cancel_event.details)


def test_audit_feed_is_admin_only(audit_client, async_session_factory) -> None:
    admin = asyncio.run(_create_user(async_session_factory, email="audit-feed-admin@example.com", password="admin-password-1", role="admin"))
    viewer = asyncio.run(_create_user(async_session_factory, email="audit-feed-viewer@example.com", password="viewer-password-1", role="viewer"))

    admin_response = audit_client.get("/api/v1/admin/audit-events", headers=_auth_header(admin))
    viewer_response = audit_client.get("/api/v1/admin/audit-events", headers=_auth_header(viewer))

    assert admin_response.status_code == 200, admin_response.text
    assert set(admin_response.json()) >= {"items", "total", "page", "page_size"}
    assert viewer_response.status_code == 403
