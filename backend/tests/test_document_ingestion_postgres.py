import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.document.storage import DocumentStorage
from app.models import Book, Chapter, Segment

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION_TESTS"),
    reason="PostgreSQL integration tests run only with RUN_INTEGRATION_TESTS=1",
)


def build_session_factory():
    database_url = os.getenv("DATABASE_URL", settings.database_url)
    engine = create_async_engine(database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


async def _cleanup(session: AsyncSession) -> None:
    await session.execute(text("DELETE FROM segments"))
    await session.execute(text("DELETE FROM chapters"))
    await session.execute(text("DELETE FROM books"))
    await session.commit()


@pytest.mark.asyncio
async def test_document_ingestion_transaction_persists_and_rolls_back() -> None:
    engine, session_factory = build_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup(session)

            book = Book(
                title="Postgres ingest test",
                author="Audit",
                file_path="relative-key.docx",
                file_type="docx",
                language="en",
                status="parsed",
            )
            session.add(book)
            await session.flush()

            chapter = Chapter(
                book_id=book.id,
                chapter_number=1,
                title="Introduction",
                content="This is the chapter text.",
                status="segmented",
            )
            session.add(chapter)
            await session.flush()

            segment = Segment(
                chapter_id=chapter.id,
                segment_number=1,
                original_text="This is the segment text.",
                translated_text=None,
                status="pending",
            )
            session.add(segment)
            await session.commit()

            book_count = await session.execute(text("SELECT COUNT(*) FROM books"))
            chapter_count = await session.execute(text("SELECT COUNT(*) FROM chapters"))
            segment_count = await session.execute(text("SELECT COUNT(*) FROM segments"))

            assert book_count.scalar_one() == 1
            assert chapter_count.scalar_one() == 1
            assert segment_count.scalar_one() == 1

            await session.execute(text("DELETE FROM segments WHERE chapter_id = :chapter_id"), {"chapter_id": chapter.id})
            await session.execute(text("DELETE FROM chapters WHERE id = :chapter_id"), {"chapter_id": chapter.id})
            await session.execute(text("DELETE FROM books WHERE id = :book_id"), {"book_id": book.id})
            await session.commit()

            assert await session.execute(text("SELECT COUNT(*) FROM books")).scalar_one() == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_document_ingestion_rollback_cleans_partial_rows_and_file() -> None:
    engine, session_factory = build_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup(session)

            storage = DocumentStorage(Path("/tmp/booktranslate-integration-cleanup"))
            file_name = storage.build_safe_name("sample.docx")
            final_path = storage.base_dir / file_name
            final_path.write_bytes(b"test-docx-bytes")

            try:
                book = Book(
                    title="Should rollback",
                    author="Audit",
                    file_path=file_name,
                    file_type="docx",
                    language="en",
                    status="parsed",
                )
                session.add(book)
                await session.flush()

                chapter = Chapter(
                    book_id=book.id,
                    chapter_number=1,
                    title="Chunk",
                    content="Content",
                    status="segmented",
                )
                session.add(chapter)
                await session.flush()

                await session.rollback()
                assert await session.execute(text("SELECT COUNT(*) FROM books")).scalar_one() == 0
                assert await session.execute(text("SELECT COUNT(*) FROM chapters")).scalar_one() == 0
            finally:
                storage.cleanup(file_name)
                assert not final_path.exists()
    finally:
        await engine.dispose()
