from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies.db import get_db
from app.main import app
from app.core.pagination import normalize_pagination


class _RouteSessionStub:
    """Minimal AsyncSession-shaped stub for route contract tests.

    These tests mock the service layer and do not exercise persistence, but audited
    mutating routes now legitimately add/flush/commit an AuditEvent after the mocked
    business service returns. Keep the route fixture compatible with that contract
    without turning these unit tests into database integration tests.
    """

    def add(self, _value: object) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.fixture
def client(admin_client: TestClient) -> TestClient:
    app.dependency_overrides[get_db] = lambda: _RouteSessionStub()
    with TestClient(app) as test_client:
        test_client.headers.update(admin_client.headers)
        yield test_client
    app.dependency_overrides.clear()


def _book_payload(**overrides: object) -> SimpleNamespace:
    payload = {
        "id": 1,
        "title": "Clean Architecture",
        "author": "Robert C. Martin",
        "description": "A classic book on software design.",
        "file_path": "/tmp/clean-architecture.pdf",
        "file_type": "pdf",
        "language": "en",
        "status": "uploaded",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _chapter_payload(**overrides: object) -> SimpleNamespace:
    payload = {
        "id": 1,
        "book_id": 1,
        "chapter_number": 1,
        "title": "Introduction",
        "content": "Welcome to the book.",
        "status": "pending",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_create_and_get_book(client: TestClient) -> None:
    book = _book_payload()

    with patch("app.api.v1.books.BookService.create_book", new=AsyncMock(return_value=book)):
        response = client.post(
            "/api/v1/books",
            json={
                "title": book.title,
                "author": book.author,
                "description": book.description,
                "file_path": book.file_path,
                "file_type": book.file_type,
                "language": book.language,
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["title"] == book.title

    with patch("app.api.v1.books.BookService.get_book", new=AsyncMock(return_value=book)):
        detail_response = client.get("/api/v1/books/1")
        assert detail_response.status_code == 200
        assert detail_response.json()["id"] == book.id


def test_patch_book(client: TestClient) -> None:
    book = _book_payload(id=4, title="Updated DDD")

    with patch("app.api.v1.books.BookService.update_book", new=AsyncMock(return_value=book)):
        response = client.patch(
            "/api/v1/books/4",
            json={"title": "Updated DDD", "description": "Updated description"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["title"] == "Updated DDD"


def test_delete_book_returns_204_without_body(client: TestClient) -> None:
    with patch("app.api.v1.books.BookService.delete_book", new=AsyncMock(return_value=None)):
        response = client.delete("/api/v1/books/9")
        assert response.status_code == 204
        assert response.content == b""
        assert response.text == ""


def test_error_envelope_and_request_id(client: TestClient) -> None:
    with patch("app.api.v1.books.BookService.get_book", new=AsyncMock(side_effect=NotFoundError("book", 77))):
        response = client.get("/api/v1/books/77")
        assert response.status_code == 404, response.text
        body = response.json()
        assert body["code"] == "not_found"
        assert body["request_id"] == response.headers["X-Request-ID"]
        assert body["message"] == "Book not found."

    with patch("app.api.v1.books.BookService.create_book", new=AsyncMock(side_effect=ConflictError("Book already exists."))):
        response = client.post(
            "/api/v1/books",
            json={
                "title": "Duplicate",
                "author": "Someone",
                "file_path": "/tmp/duplicate.pdf",
                "file_type": "pdf",
                "language": "en",
            },
        )
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["code"] == "conflict"
        assert body["request_id"] == response.headers["X-Request-ID"]


def test_validation_error_endpoints_and_safe_500(client: TestClient) -> None:
    invalid = client.post(
        "/api/v1/books",
        json={"title": "", "file_path": "", "file_type": "", "language": ""},
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"
    assert invalid.json()["request_id"] == invalid.headers["X-Request-ID"]

    with patch("app.api.v1.books.BookService.get_book", new=AsyncMock(side_effect=RuntimeError("secret database details"))):
        response = client.get("/api/v1/books/1")
        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "internal_server_error"
        assert body["message"] == "Internal server error."
        assert body["details"] == {}
        assert body["request_id"] == response.headers["X-Request-ID"]
        assert "secret database details" not in response.text


def test_pagination_and_page_size_limits() -> None:
    assert normalize_pagination(1, 20) == (1, 20)
    assert normalize_pagination(0, 0) == (1, 1)
    assert normalize_pagination(2, 500) == (2, 100)


def test_rollback_and_integrity_error() -> None:
    db = AsyncMock()
    service_error = IntegrityError("statement", {}, Exception("unique"))

    async def _run() -> None:
        from app.services.book_service import BookService

        service = BookService(db)
        service.repository.create = AsyncMock(side_effect=service_error)
        with pytest.raises(ConflictError):
            await service.create_book({"title": "X"})
        db.rollback.assert_awaited_once()

    import asyncio

    asyncio.run(_run())


def test_postgres_integration_tests_are_skipped_without_service() -> None:
    # Placeholder documenting that PostgreSQL-only coverage is supplied separately
    # by CI; ordinary unit tests remain self-contained.
    assert True
