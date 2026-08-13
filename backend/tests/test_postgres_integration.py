import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings


pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION_TESTS"),
    reason="PostgreSQL integration tests run only in CI with RUN_INTEGRATION_TESTS=1",
)


def build_test_session_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    database_url = os.getenv("DATABASE_URL", settings.database_url)
    engine = create_async_engine(database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


async def _cleanup(session) -> None:
    await session.execute(text("DELETE FROM segments"))
    await session.execute(text("DELETE FROM chapters"))
    await session.execute(text("DELETE FROM books"))
    await session.commit()


@pytest.mark.asyncio
async def test_crud_book_chapter_segment_and_foreign_keys() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
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

            book_row = await session.execute(text("SELECT title FROM books WHERE id = :id"), {"id": book_id})
            assert book_row.one()[0] == "Book One"

            chapter_row = await session.execute(text("SELECT book_id FROM chapters WHERE id = :id"), {"id": chapter_id})
            assert chapter_row.one()[0] == book_id

            segment_row = await session.execute(text("SELECT chapter_id FROM segments WHERE id = :id"), {"id": segment_id})
            assert segment_row.one()[0] == chapter_id

            await session.execute(text("DELETE FROM books WHERE id = :id"), {"id": book_id})
            await session.commit()

            chapter_count = await session.execute(
                text("SELECT COUNT(*) FROM chapters WHERE book_id = :book_id"), {"book_id": book_id}
            )
            segment_count = await session.execute(
                text("SELECT COUNT(*) FROM segments WHERE chapter_id = :chapter_id"), {"chapter_id": chapter_id}
            )
            assert chapter_count.scalar_one() == 0
            assert segment_count.scalar_one() == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_numbers_are_rejected_within_scope_but_allowed_across_entities() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup(session)

            book_a_id = (
                await session.execute(
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
            ).scalar_one()
            book_b_id = (
                await session.execute(
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
            ).scalar_one()

            chapter_a_id = (
                await session.execute(
                    text(
                        "INSERT INTO chapters (book_id, chapter_number, title, content, status) VALUES "
                        "(:book_id, :chapter_number, :title, :content, :status) RETURNING id"
                    ),
                    {"book_id": book_a_id, "chapter_number": 1, "title": "A1", "content": "A1", "status": "pending"},
                )
            ).scalar_one()
            chapter_b_id = (
                await session.execute(
                    text(
                        "INSERT INTO chapters (book_id, chapter_number, title, content, status) VALUES "
                        "(:book_id, :chapter_number, :title, :content, :status) RETURNING id"
                    ),
                    {"book_id": book_b_id, "chapter_number": 1, "title": "B1", "content": "B1", "status": "pending"},
                )
            ).scalar_one()
            await session.commit()

            try:
                await session.execute(
                    text(
                        "INSERT INTO chapters (book_id, chapter_number, title, content, status) VALUES "
                        "(:book_id, :chapter_number, :title, :content, :status)"
                    ),
                    {"book_id": book_a_id, "chapter_number": 1, "title": "A2", "content": "A2", "status": "pending"},
                )
                await session.commit()
                pytest.fail("Expected IntegrityError for duplicate chapter number within the same book")
            except IntegrityError:
                await session.rollback()

            chapter_a_count = await session.execute(
                text("SELECT COUNT(*) FROM chapters WHERE book_id = :book_id"), {"book_id": book_a_id}
            )
            chapter_b_count = await session.execute(
                text("SELECT COUNT(*) FROM chapters WHERE book_id = :book_id"), {"book_id": book_b_id}
            )
            assert chapter_a_count.scalar_one() == 1
            assert chapter_b_count.scalar_one() == 1

            segment_a_id = (
                await session.execute(
                    text(
                        "INSERT INTO segments (chapter_id, segment_number, original_text, translated_text, status) VALUES "
                        "(:chapter_id, :segment_number, :original_text, :translated_text, :status) RETURNING id"
                    ),
                    {"chapter_id": chapter_a_id, "segment_number": 1, "original_text": "A-1", "translated_text": "A-1-tr", "status": "pending"},
                )
            ).scalar_one()
            await session.commit()

            try:
                await session.execute(
                    text(
                        "INSERT INTO segments (chapter_id, segment_number, original_text, translated_text, status) VALUES "
                        "(:chapter_id, :segment_number, :original_text, :translated_text, :status)"
                    ),
                    {"chapter_id": chapter_a_id, "segment_number": 1, "original_text": "A-dup", "translated_text": "A-dup-tr", "status": "pending"},
                )
                await session.commit()
                pytest.fail("Expected IntegrityError for duplicate segment number within the same chapter")
            except IntegrityError:
                await session.rollback()

            segment_a_count = await session.execute(
                text("SELECT COUNT(*) FROM segments WHERE chapter_id = :chapter_id"), {"chapter_id": chapter_a_id}
            )
            assert segment_a_count.scalar_one() == 1

            segment_b_id = (
                await session.execute(
                    text(
                        "INSERT INTO segments (chapter_id, segment_number, original_text, translated_text, status) VALUES "
                        "(:chapter_id, :segment_number, :original_text, :translated_text, :status) RETURNING id"
                    ),
                    {"chapter_id": chapter_b_id, "segment_number": 1, "original_text": "B-1", "translated_text": "B-1-tr", "status": "pending"},
                )
            ).scalar_one()
            await session.commit()

            segment_b_count = await session.execute(
                text("SELECT COUNT(*) FROM segments WHERE chapter_id = :chapter_id"), {"chapter_id": chapter_b_id}
            )
            assert segment_b_count.scalar_one() == 1
            assert segment_a_id != segment_b_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rollback_after_integrity_error() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup(session)

            book_id = (
                await session.execute(
                    text(
                        "INSERT INTO books (title, author, file_path, file_type, language, status) VALUES "
                        "(:title, :author, :file_path, :file_type, :language, :status) RETURNING id"
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
            ).scalar_one()
            await session.commit()

            async with session_factory() as session_two:
                try:
                    await session_two.execute(
                        text(
                            "INSERT INTO chapters (book_id, chapter_number, title, content, status) VALUES "
                            "(:book_id, :chapter_number, :title, :content, :status)"
                        ),
                        {"book_id": book_id, "chapter_number": 1, "title": "One", "content": "Body", "status": "pending"},
                    )
                    await session_two.execute(
                        text(
                            "INSERT INTO chapters (book_id, chapter_number, title, content, status) VALUES "
                            "(:book_id, :chapter_number, :title, :content, :status)"
                        ),
                        {"book_id": book_id, "chapter_number": 1, "title": "Two", "content": "Body", "status": "pending"},
                    )
                    await session_two.commit()
                    pytest.fail("Expected IntegrityError for duplicate chapter number in the same book")
                except IntegrityError:
                    await session_two.rollback()

                count = await session_two.execute(
                    text("SELECT COUNT(*) FROM chapters WHERE book_id = :book_id"), {"book_id": book_id}
                )
                assert count.scalar_one() == 1

        async with session_factory() as verify_session:
            count = await verify_session.execute(
                text("SELECT COUNT(*) FROM chapters WHERE book_id = :book_id"), {"book_id": book_id}
            )
            assert count.scalar_one() == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_001_to_002_constraints_exist() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            tables = await session.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid = 'chapters'::regclass "
                    "OR conrelid = 'segments'::regclass;"
                )
            )
            names = {row[0] for row in tables.fetchall()}
            assert "uq_chapters_book_number" in names
            assert "uq_segments_chapter_number" in names
    finally:
        await engine.dispose()
