import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import async_session_factory
from app.main import app


pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION_TESTS"),
    reason="PostgreSQL integration tests run only in CI with RUN_INTEGRATION_TESTS=1",
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
async def session():
    async with async_session_factory() as session:
        yield session


async def _cleanup(session) -> None:
    await session.execute(text("DELETE FROM segments"))
    await session.execute(text("DELETE FROM chapters"))
    await session.execute(text("DELETE FROM books"))
    await session.commit()


@pytest.mark.asyncio
async def test_crud_book_chapter_segment_and_foreign_keys() -> None:
    async with async_session_factory() as session:
        await _cleanup(session)

        result = await session.execute(
            text(
                "INSERT INTO books (title, author, file_path, file_type, language, status) "
                "VALUES (:title, :author, :file_path, :file_type, :language, :status) RETURNING id"
            ),
            {
                "title": "Book One",
                "author": "Author One",
                "file_path": "/tmp/book-one.pdf",
                "file_type": "pdf",
                "language": "en",
                "status": "uploaded",
            },
        )
        book_id = result.scalar_one()

        ch_result = await session.execute(
            text(
                "INSERT INTO chapters (book_id, chapter_number, title, content, status) "
                "VALUES (:book_id, :chapter_number, :title, :content, :status) RETURNING id"
            ),
            {
                "book_id": book_id,
                "chapter_number": 1,
                "title": "Intro",
                "content": "Hello",
                "status": "pending",
            },
        )
        chapter_id = ch_result.scalar_one()

        seg_result = await session.execute(
            text(
                "INSERT INTO segments (chapter_id, segment_number, original_text, translated_text, status) "
                "VALUES (:chapter_id, :segment_number, :original_text, :translated_text, :status) RETURNING id"
            ),
            {
                "chapter_id": chapter_id,
                "segment_number": 1,
                "original_text": "Original",
                "translated_text": "Translated",
                "status": "pending",
            },
        )
        segment_id = seg_result.scalar_one()

        book_row = await session.execute(text("SELECT id, title FROM books WHERE id = :id"), {"id": book_id})
        assert book_row.scalar_one()[1] == "Book One"

        chapter_row = await session.execute(text("SELECT id, book_id FROM chapters WHERE id = :id"), {"id": chapter_id})
        assert chapter_row.scalar_one()[1] == book_id

        segment_row = await session.execute(text("SELECT id, chapter_id FROM segments WHERE id = :id"), {"id": segment_id})
        assert segment_row.scalar_one()[1] == chapter_id

        await session.execute(text("DELETE FROM books WHERE id = :id"), {"id": book_id})
        await session.commit()

        chapter_count = await session.execute(text("SELECT COUNT(*) FROM chapters WHERE id = :id"), {"id": chapter_id})
        segment_count = await session.execute(text("SELECT COUNT(*) FROM segments WHERE id = :id"), {"id": segment_id})
        assert chapter_count.scalar_one() == 0
        assert segment_count.scalar_one() == 0


@pytest.mark.asyncio
async def test_duplicate_numbers_are_rejected_within_scope_but_allowed_across_entities() -> None:
    async with async_session_factory() as session:
        await _cleanup(session)

        book_a = await session.execute(
            text(
                "INSERT INTO books (title, author, file_path, file_type, language, status) VALUES "
                "(:title, :author, :file_path, :file_type, :language, :status) RETURNING id"
            ),
            {
                "title": "Book A",
                "author": "A",
                "file_path": "/tmp/a.pdf",
                "file_type": "pdf",
                "language": "en",
                "status": "uploaded",
            },
        )
        book_a_id = book_a.scalar_one()
        book_b = await session.execute(
            text(
                "INSERT INTO books (title, author, file_path, file_type, language, status) VALUES "
                "(:title, :author, :file_path, :file_type, :language, :status) RETURNING id"
            ),
            {
                "title": "Book B",
                "author": "B",
                "file_path": "/tmp/b.pdf",
                "file_type": "pdf",
                "language": "en",
                "status": "uploaded",
            },
        )
        book_b_id = book_b.scalar_one()

        await session.execute(
            text(
                "INSERT INTO chapters (book_id, chapter_number, title, content, status) VALUES "
                "(:book_id, :chapter_number, :title, :content, :status)"
            ),
            {"book_id": book_a_id, "chapter_number": 1, "title": "A1", "content": "A1", "status": "pending"},
        )
        await session.execute(
            text(
                "INSERT INTO chapters (book_id, chapter_number, title, content, status) VALUES "
                "(:book_id, :chapter_number, :title, :content, :status)"
            ),
            {"book_id": book_b_id, "chapter_number": 1, "title": "B1", "content": "B1", "status": "pending"},
        )
        await session.commit()

        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO chapters (book_id, chapter_number, title, content, status) VALUES "
                    "(:book_id, :chapter_number, :title, :content, :status)"
                ),
                {"book_id": book_a_id, "chapter_number": 1, "title": "A2", "content": "A2", "status": "pending"},
            )
            await session.commit()

        chapter_a = await session.execute(text("SELECT COUNT(*) FROM chapters WHERE book_id = :book_id"), {"book_id": book_a_id})
        assert chapter_a.scalar_one() == 2

        chapter_b = await session.execute(text("SELECT COUNT(*) FROM chapters WHERE book_id = :book_id"), {"book_id": book_b_id})
        assert chapter_b.scalar_one() == 1

        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO segments (chapter_id, segment_number, original_text, translated_text, status) VALUES "
                    "(:chapter_id, :segment_number, :original_text, :translated_text, :status)"
                ),
                {"chapter_id": 1, "segment_number": 1, "original_text": "Dup", "translated_text": "Dup", "status": "pending"},
            )
            await session.commit()


@pytest.mark.asyncio
async def test_rollback_after_integrity_error() -> None:
    async with async_session_factory() as session:
        await _cleanup(session)

        await session.execute(
            text(
                "INSERT INTO books (title, author, file_path, file_type, language, status) VALUES "
                "(:title, :author, :file_path, :file_type, :language, :status)"
            ),
            {
                "title": "Rollback Book",
                "author": "A",
                "file_path": "/tmp/rb.pdf",
                "file_type": "pdf",
                "language": "en",
                "status": "uploaded",
            },
        )
        await session.commit()

        try:
            await session.execute(
                text(
                    "INSERT INTO chapters (book_id, chapter_number, title, content, status) VALUES "
                    "(:book_id, :chapter_number, :title, :content, :status)"
                ),
                {"book_id": 1, "chapter_number": 1, "title": "One", "content": "Body", "status": "pending"},
            )
            await session.execute(
                text(
                    "INSERT INTO chapters (book_id, chapter_number, title, content, status) VALUES "
                    "(:book_id, :chapter_number, :title, :content, :status)"
                ),
                {"book_id": 1, "chapter_number": 1, "title": "Two", "content": "Body", "status": "pending"},
            )
            await session.commit()
        except IntegrityError:
            await session.rollback()

        count = await session.execute(text("SELECT COUNT(*) FROM chapters WHERE book_id = :book_id"), {"book_id": 1})
        assert count.scalar_one() == 1


@pytest.mark.asyncio
async def test_migration_001_to_002_constraints_exist() -> None:
    async with async_session_factory() as session:
        tables = await session.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'chapters'::regclass "
                "OR conrelid = 'segments'::regclass;"
            )
        )
        names = {row[0] for row in tables.fetchall()}
        assert "uq_chapters_book_number" in names
        assert "uq_segments_chapter_number" in names
