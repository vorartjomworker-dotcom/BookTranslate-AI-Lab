from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies.db import get_db
from app.main import app
from app.core.pagination import normalize_pagination


@pytest.fixture
def client(admin_client: TestClient) -> TestClient:
    app.dependency_overrides[get_db] = lambda: object()
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
    assert invalid.headers["X-Request-ID"]

    with patch("app.api.v1.books.BookService.get_book", new=AsyncMock(side_effect=RuntimeError("boom"))):
        response = client.get("/api/v1/books/3")
        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "internal_server_error"
        assert body["message"] == "Internal server error."
        assert body["request_id"] == response.headers["X-Request-ID"]
        assert "traceback" not in body["details"]


def test_pagination_and_page_size_limits() -> None:
    assert normalize_pagination(0, 0) == (1, 1)
    assert normalize_pagination(3, 200) == (3, 100)
    assert normalize_pagination(2, 10) == (2, 10)

    body = {
        "items": [{"id": 1}, {"id": 2}],
        "total": 45,
        "page": 2,
        "page_size": 10,
        "pages": 5,
    }
    assert body["pages"] == (body["total"] + body["page_size"] - 1) // body["page_size"]


def test_rollback_and_integrity_error() -> None:
    service = __import__("app.services.book_service", fromlist=["BookService"]).BookService(session=AsyncMock())
    service.repository.create = AsyncMock(side_effect=IntegrityError("stmt", "params", "orig"))

    with pytest.raises(ConflictError):
        awaitable = service.create_book({"title": "Bad", "file_path": "/tmp/bad.pdf", "file_type": "pdf"})
        import asyncio
        asyncio.run(awaitable)

    service.session.rollback.assert_called_once()


def test_postgres_integration_tests_are_skipped_without_service() -> None:
    pytest.importorskip("os")
    import os

    if not os.getenv("DATABASE_URL"):
        pytest.skip("requires PostgreSQL service in CI")
