from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import Book, Chapter, Segment, TranslationJob
from app.workers.translator_worker import TranslatorWorker

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION_TESTS"),
    reason="PostgreSQL integration tests run only in CI with RUN_INTEGRATION_TESTS=1",
)


def build_test_session_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    database_url = os.getenv("DATABASE_URL", settings.database_url)
    engine = create_async_engine(database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


@pytest.mark.asyncio
async def test_concurrent_workers_only_one_claims_queued_job(monkeypatch) -> None:
    engine, session_factory = build_test_session_factory()
    book_id: int | None = None
    chapter_id: int | None = None
    segment_id: int | None = None
    job_id: int | None = None
    try:
        async with session_factory() as session:
            book = Book(title="__worker_claim_race__", file_path="/tmp/worker-claim.epub", file_type="epub", language="en")
            session.add(book)
            await session.flush()
            book_id = book.id

            chapter = Chapter(book_id=book.id, chapter_number=991, title="worker claim", content="worker claim")
            session.add(chapter)
            await session.flush()
            chapter_id = chapter.id

            segment = Segment(chapter_id=chapter.id, segment_number=991, original_text="claim me once", status="pending")
            session.add(segment)
            await session.flush()
            segment_id = segment.id

            job = TranslationJob(
                segment_id=segment.id,
                provider="openai",
                model="gpt-4o",
                status="queued",
                attempt=0,
                max_attempts=3,
            )
            session.add(job)
            await session.commit()
            job_id = job.id

        monkeypatch.setattr("app.workers.translator_worker.async_session_factory", session_factory)
        first = TranslatorWorker()
        second = TranslatorWorker()

        claims = await asyncio.gather(
            first._claim_job_for_processing(int(job_id)),
            second._claim_job_for_processing(int(job_id)),
        )

        assert sorted(claims) == ["busy", "claimed"]

        async with session_factory() as session:
            reloaded = await session.get(TranslationJob, job_id)
            assert reloaded is not None
            assert reloaded.status == "running"
            assert reloaded.started_at is not None
    finally:
        async with session_factory() as session:
            if job_id is not None:
                job = await session.get(TranslationJob, job_id)
                if job is not None:
                    await session.delete(job)
            if segment_id is not None:
                segment = await session.get(Segment, segment_id)
                if segment is not None:
                    await session.delete(segment)
            if chapter_id is not None:
                chapter = await session.get(Chapter, chapter_id)
                if chapter is not None:
                    await session.delete(chapter)
            if book_id is not None:
                book = await session.get(Book, book_id)
                if book is not None:
                    await session.delete(book)
            await session.commit()
        await engine.dispose()
