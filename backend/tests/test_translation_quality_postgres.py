from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import Book, Chapter, Segment, TranslationJob, TranslationQualityReport
from app.quality.deterministic import sha256_text
from app.quality.service import QualityAssuranceService

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION_TESTS"),
    reason="PostgreSQL integration tests run only with RUN_INTEGRATION_TESTS=1",
)


def build_test_session_factory():
    database_url = os.getenv("DATABASE_URL", settings.database_url)
    engine = create_async_engine(database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


async def _cleanup_quality_tables(session: AsyncSession) -> None:
    await session.execute(text("DELETE FROM translation_quality_reports"))
    await session.execute(text("DELETE FROM translation_jobs"))
    await session.execute(text("DELETE FROM segments"))
    await session.execute(text("DELETE FROM chapters"))
    await session.execute(text("DELETE FROM books"))
    await session.commit()


async def _seed_book_chapter_segment(session: AsyncSession, *, book_title: str = "QA book", segment_number: int = 1):
    book = Book(
        title=book_title,
        author="QA",
        file_path="/tmp/qa.pdf",
        file_type="pdf",
        language="en",
    )
    session.add(book)
    await session.flush()

    chapter = Chapter(
        book_id=book.id,
        chapter_number=1,
        title="Chapter 1",
        content="Chapter content",
        status="translated",
    )
    session.add(chapter)
    await session.flush()

    segment = Segment(
        chapter_id=chapter.id,
        segment_number=segment_number,
        original_text="Hello world.",
        translated_text="Hola mundo.",
        status="translated",
    )
    session.add(segment)
    await session.flush()
    return book, chapter, segment


async def _insert_valid_report(
    session: AsyncSession,
    *,
    segment_id: int,
    translation_job_id: int | None = None,
    evaluator_version: str = "1.0.0",
    deterministic_score: int = 90,
    ai_score: int | None = 85,
    overall_score: int = 88,
    status: str = "passed",
    source_checksum: str | None = None,
    translated_checksum: str | None = None,
    issues: list[dict] | None = None,
    mode: str = "deterministic",
) -> TranslationQualityReport:
    source_checksum = source_checksum or sha256_text("Hello world.")
    translated_checksum = translated_checksum or sha256_text("Hola mundo.")
    issues = issues or [{"code": "ok", "severity": "info", "message": "Looks good", "field": "translation", "score_impact": 0}]

    report = TranslationQualityReport(
        segment_id=segment_id,
        translation_job_id=translation_job_id,
        evaluator_version=evaluator_version,
        mode=mode,
        deterministic_score=deterministic_score,
        ai_score=ai_score,
        overall_score=overall_score,
        evaluator_error_code=None,
        status=status,
        summary="Looks good",
        provider="openai",
        model="gpt-4o",
        source_language="en",
        target_language="ru",
        source_checksum=source_checksum,
        translated_checksum=translated_checksum,
        issues=issues,
    )
    session.add(report)
    await session.flush()
    return report


@pytest.mark.asyncio
async def test_translation_quality_reports_migration_004_applied() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            tables = await session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                    "AND table_name = 'translation_quality_reports'"
                )
            )
            assert tables.scalar_one() == "translation_quality_reports"

            columns = await session.execute(
                text(
                    "SELECT column_name, data_type, udt_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'translation_quality_reports' "
                    "ORDER BY ordinal_position"
                )
            )
            columns_by_name = {row[0]: row for row in columns.all()}
            required_columns = {
                "id",
                "segment_id",
                "translation_job_id",
                "evaluator_version",
                "mode",
                "deterministic_score",
                "ai_score",
                "overall_score",
                "evaluator_error_code",
                "status",
                "issues",
                "summary",
                "provider",
                "model",
                "source_language",
                "target_language",
                "source_checksum",
                "translated_checksum",
                "created_at",
                "updated_at",
            }
            assert required_columns.issubset(columns_by_name)
            assert columns_by_name["issues"][1] == "jsonb" or columns_by_name["issues"][2] == "jsonb"

            check_constraints = await session.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid = 'translation_quality_reports'::regclass "
                    "AND contype = 'c' ORDER BY conname"
                )
            )
            check_names = {row[0] for row in check_constraints.all()}
            assert "ck_translation_quality_reports_deterministic_score_range" in check_names
            assert "ck_translation_quality_reports_ai_score_range" in check_names
            assert "ck_translation_quality_reports_overall_score_range" in check_names
            assert "ck_translation_quality_reports_status" in check_names
            assert "ck_translation_quality_reports_mode" in check_names

            indexes = await session.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'translation_quality_reports' "
                    "ORDER BY indexname"
                )
            )
            index_names = {row[0] for row in indexes.all()}
            assert "ix_translation_quality_reports_segment_id" in index_names
            assert "ix_translation_quality_reports_translation_job_id" in index_names
            assert "ix_translation_quality_reports_status" in index_names
            assert "uq_translation_quality_reports_job_evaluator" in index_names
            assert "uq_translation_quality_reports_segment_evaluator" in index_names
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_round_trip_with_jsonb_issues() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            await session.commit()

            issues = [
                {"code": "terminology", "severity": "warning", "message": "Literal mismatch", "field": "translation", "score_impact": 7},
                {"code": "style", "severity": "info", "message": "Tone is slightly formal", "field": "translation", "score_impact": 2},
            ]
            report = TranslationQualityReport(
                segment_id=segment.id,
                translation_job_id=None,
                evaluator_version="1.0.0",
                mode="full",
                deterministic_score=92,
                ai_score=89,
                overall_score=91,
                evaluator_error_code=None,
                status="passed",
                summary="Good translation",
                provider="openai",
                model="gpt-4o",
                source_language="en",
                target_language="ru",
                source_checksum=sha256_text("Hello world."),
                translated_checksum=sha256_text("Hola mundo."),
                issues=issues,
            )
            session.add(report)
            await session.commit()
            await session.refresh(report)

            stored = await session.execute(
                text("SELECT issues::text FROM translation_quality_reports WHERE id = :id"),
                {"id": report.id},
            )
            payload = json.loads(stored.scalar_one())
            assert payload[0]["code"] == "terminology"
            assert payload[1]["score_impact"] == 2
            assert report.issues[0]["message"] == "Literal mismatch"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_rejects_negative_deterministic_score() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            await session.commit()

            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO translation_quality_reports (segment_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                        "VALUES (:segment_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                    ),
                    {
                        "segment_id": segment.id,
                        "evaluator_version": "1.0.0",
                        "mode": "deterministic",
                        "deterministic_score": -1,
                        "overall_score": 90,
                        "status": "passed",
                        "summary": "bad",
                        "source_checksum": sha256_text("Hello world."),
                        "translated_checksum": sha256_text("Hola mundo."),
                        "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
                    },
                )
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_rejects_over_100_deterministic_score() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            await session.commit()

            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO translation_quality_reports (segment_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                        "VALUES (:segment_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                    ),
                    {
                        "segment_id": segment.id,
                        "evaluator_version": "1.0.0",
                        "mode": "deterministic",
                        "deterministic_score": 101,
                        "overall_score": 90,
                        "status": "passed",
                        "summary": "bad",
                        "source_checksum": sha256_text("Hello world."),
                        "translated_checksum": sha256_text("Hola mundo."),
                        "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
                    },
                )
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_rejects_ai_score_below_zero() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            await session.commit()

            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO translation_quality_reports (segment_id, evaluator_version, mode, deterministic_score, ai_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                        "VALUES (:segment_id, :evaluator_version, :mode, :deterministic_score, :ai_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                    ),
                    {
                        "segment_id": segment.id,
                        "evaluator_version": "1.0.0",
                        "mode": "deterministic",
                        "deterministic_score": 90,
                        "ai_score": -1,
                        "overall_score": 90,
                        "status": "passed",
                        "summary": "bad",
                        "source_checksum": sha256_text("Hello world."),
                        "translated_checksum": sha256_text("Hola mundo."),
                        "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
                    },
                )
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_rejects_ai_score_above_100() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            await session.commit()

            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO translation_quality_reports (segment_id, evaluator_version, mode, deterministic_score, ai_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                        "VALUES (:segment_id, :evaluator_version, :mode, :deterministic_score, :ai_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                    ),
                    {
                        "segment_id": segment.id,
                        "evaluator_version": "1.0.0",
                        "mode": "deterministic",
                        "deterministic_score": 90,
                        "ai_score": 101,
                        "overall_score": 90,
                        "status": "passed",
                        "summary": "bad",
                        "source_checksum": sha256_text("Hello world."),
                        "translated_checksum": sha256_text("Hola mundo."),
                        "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
                    },
                )
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_rejects_overall_score_below_zero() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            await session.commit()

            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO translation_quality_reports (segment_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                        "VALUES (:segment_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                    ),
                    {
                        "segment_id": segment.id,
                        "evaluator_version": "1.0.0",
                        "mode": "deterministic",
                        "deterministic_score": 90,
                        "overall_score": -1,
                        "status": "passed",
                        "summary": "bad",
                        "source_checksum": sha256_text("Hello world."),
                        "translated_checksum": sha256_text("Hola mundo."),
                        "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
                    },
                )
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_rejects_overall_score_above_100() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            await session.commit()

            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO translation_quality_reports (segment_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                        "VALUES (:segment_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                    ),
                    {
                        "segment_id": segment.id,
                        "evaluator_version": "1.0.0",
                        "mode": "deterministic",
                        "deterministic_score": 90,
                        "overall_score": 101,
                        "status": "passed",
                        "summary": "bad",
                        "source_checksum": sha256_text("Hello world."),
                        "translated_checksum": sha256_text("Hola mundo."),
                        "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
                    },
                )
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_rejects_unknown_status() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            await session.commit()

            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO translation_quality_reports (segment_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                        "VALUES (:segment_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                    ),
                    {
                        "segment_id": segment.id,
                        "evaluator_version": "1.0.0",
                        "mode": "deterministic",
                        "deterministic_score": 90,
                        "overall_score": 90,
                        "status": "archived",
                        "summary": "bad",
                        "source_checksum": sha256_text("Hello world."),
                        "translated_checksum": sha256_text("Hola mundo."),
                        "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
                    },
                )
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_rejects_unknown_segment_fk() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)

            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO translation_quality_reports (segment_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                        "VALUES (:segment_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                    ),
                    {
                        "segment_id": 999999,
                        "evaluator_version": "1.0.0",
                        "mode": "deterministic",
                        "deterministic_score": 90,
                        "overall_score": 90,
                        "status": "passed",
                        "summary": "bad",
                        "source_checksum": sha256_text("Hello world."),
                        "translated_checksum": sha256_text("Hola mundo."),
                        "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
                    },
                )
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_rejects_duplicate_job_evaluator() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            job = TranslationJob(segment_id=segment.id, provider="openai", model="gpt-4o", status="completed", attempt=1, max_attempts=3)
            session.add(job)
            await session.flush()
            await session.commit()

            insert_sql = text(
                "INSERT INTO translation_quality_reports (segment_id, translation_job_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                "VALUES (:segment_id, :translation_job_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
            )
            first_payload = {
                "segment_id": segment.id,
                "translation_job_id": job.id,
                "evaluator_version": "1.0.0",
                "mode": "deterministic",
                "deterministic_score": 90,
                "overall_score": 90,
                "status": "passed",
                "summary": "good",
                "source_checksum": sha256_text("Hello world."),
                "translated_checksum": sha256_text("Hola mundo."),
                "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
            }
            second_payload = {**first_payload, "overall_score": 92}

            await session.execute(insert_sql, first_payload)
            await session.commit()
            with pytest.raises(IntegrityError):
                await session.execute(insert_sql, second_payload)
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_allows_two_jobs_same_segment_same_version() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            job_a = TranslationJob(segment_id=segment.id, provider="openai", model="gpt-4o", status="completed", attempt=1, max_attempts=3)
            job_b = TranslationJob(segment_id=segment.id, provider="openai", model="gpt-4o", status="completed", attempt=1, max_attempts=3)
            session.add_all([job_a, job_b])
            await session.commit()

            await session.execute(
                text(
                    "INSERT INTO translation_quality_reports (segment_id, translation_job_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                    "VALUES (:segment_id, :translation_job_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                ),
                {
                    "segment_id": segment.id,
                    "translation_job_id": job_a.id,
                    "evaluator_version": "1.0.0",
                    "mode": "deterministic",
                    "deterministic_score": 90,
                    "overall_score": 90,
                    "status": "passed",
                    "summary": "first",
                    "source_checksum": sha256_text("Hello world."),
                    "translated_checksum": sha256_text("Hola mundo."),
                    "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
                },
            )
            await session.execute(
                text(
                    "INSERT INTO translation_quality_reports (segment_id, translation_job_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                    "VALUES (:segment_id, :translation_job_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                ),
                {
                    "segment_id": segment.id,
                    "translation_job_id": job_b.id,
                    "evaluator_version": "1.0.0",
                    "mode": "deterministic",
                    "deterministic_score": 86,
                    "overall_score": 86,
                    "status": "needs_review",
                    "summary": "second",
                    "source_checksum": sha256_text("Hello world."),
                    "translated_checksum": sha256_text("Hola mundo."),
                    "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
                },
            )
            await session.commit()

            count = await session.execute(
                text("SELECT COUNT(*) FROM translation_quality_reports WHERE segment_id = :segment_id"),
                {"segment_id": segment.id},
            )
            assert count.scalar_one() == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_reports_reject_duplicate_same_segment_and_checksum() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            await session.commit()

            base = {
                "segment_id": segment.id,
                "translation_job_id": None,
                "evaluator_version": "1.0.0",
                "mode": "deterministic",
                "deterministic_score": 90,
                "overall_score": 90,
                "status": "passed",
                "summary": "good",
                "source_checksum": sha256_text("Hello world."),
                "translated_checksum": sha256_text("Hola mundo."),
                "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
            }

            await session.execute(
                text(
                    "INSERT INTO translation_quality_reports (segment_id, translation_job_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                    "VALUES (:segment_id, :translation_job_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                ),
                base,
            )
            await session.commit()

            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO translation_quality_reports (segment_id, translation_job_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                        "VALUES (:segment_id, :translation_job_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                    ),
                    base,
                )
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_allows_new_manual_report_after_source_checksum_change() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            await session.commit()

            base = {
                "segment_id": segment.id,
                "translation_job_id": None,
                "evaluator_version": "1.0.0",
                "mode": "deterministic",
                "deterministic_score": 90,
                "overall_score": 90,
                "status": "passed",
                "summary": "good",
                "source_checksum": sha256_text("Hello world."),
                "translated_checksum": sha256_text("Hola mundo."),
                "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
            }
            await session.execute(
                text(
                    "INSERT INTO translation_quality_reports (segment_id, translation_job_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                    "VALUES (:segment_id, :translation_job_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                ),
                base,
            )
            await session.execute(
                text(
                    "INSERT INTO translation_quality_reports (segment_id, translation_job_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                    "VALUES (:segment_id, :translation_job_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                ),
                {**base, "source_checksum": sha256_text("Hello world!"), "summary": "new source"},
            )
            await session.commit()

            count = await session.execute(
                text("SELECT COUNT(*) FROM translation_quality_reports WHERE segment_id = :segment_id"),
                {"segment_id": segment.id},
            )
            assert count.scalar_one() == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_allows_new_manual_report_after_translated_checksum_change() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            await session.commit()

            base = {
                "segment_id": segment.id,
                "translation_job_id": None,
                "evaluator_version": "1.0.0",
                "mode": "deterministic",
                "deterministic_score": 90,
                "overall_score": 90,
                "status": "passed",
                "summary": "good",
                "source_checksum": sha256_text("Hello world."),
                "translated_checksum": sha256_text("Hola mundo."),
                "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
            }
            await session.execute(
                text(
                    "INSERT INTO translation_quality_reports (segment_id, translation_job_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                    "VALUES (:segment_id, :translation_job_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                ),
                base,
            )
            await session.execute(
                text(
                    "INSERT INTO translation_quality_reports (segment_id, translation_job_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                    "VALUES (:segment_id, :translation_job_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                ),
                {**base, "translated_checksum": sha256_text("Adios mundo."), "summary": "new translation"},
            )
            await session.commit()

            count = await session.execute(
                text("SELECT COUNT(*) FROM translation_quality_reports WHERE segment_id = :segment_id"),
                {"segment_id": segment.id},
            )
            assert count.scalar_one() == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_quality_report_rollback_leaves_no_partial_rows() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            await session.commit()

            try:
                await session.execute(
                    text(
                        "INSERT INTO translation_quality_reports (segment_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                        "VALUES (:segment_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                    ),
                    {
                        "segment_id": segment.id,
                        "evaluator_version": "1.0.0",
                        "mode": "deterministic",
                        "deterministic_score": 90,
                        "overall_score": 90,
                        "status": "passed",
                        "summary": "before",
                        "source_checksum": sha256_text("Hello world."),
                        "translated_checksum": sha256_text("Hola mundo."),
                        "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
                    },
                )
                await session.execute(
                    text(
                        "INSERT INTO translation_quality_reports (segment_id, evaluator_version, mode, deterministic_score, overall_score, status, summary, source_checksum, translated_checksum, issues) "
                        "VALUES (:segment_id, :evaluator_version, :mode, :deterministic_score, :overall_score, :status, :summary, :source_checksum, :translated_checksum, :issues)"
                    ),
                    {
                        "segment_id": segment.id,
                        "evaluator_version": "1.0.0",
                        "mode": "deterministic",
                        "deterministic_score": 80,
                        "overall_score": 80,
                        "status": "needs_review",
                        "summary": "after",
                        "source_checksum": sha256_text("Hello world."),
                        "translated_checksum": sha256_text("Hola mundo."),
                        "issues": json.dumps([{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}]),
                    },
                )
                await session.rollback()
            except IntegrityError:
                await session.rollback()

            count = await session.execute(text("SELECT COUNT(*) FROM translation_quality_reports"))
            assert count.scalar_one() == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_segment_fields_sync_atomically_with_canonical_report() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            segment.qa_score = 10
            segment.qa_status = "needs_review"
            await session.commit()

            service = QualityAssuranceService(session)
            report = await service.evaluate_segment(
                segment_id=segment.id,
                source_text="Hello world.",
                translated_text="Hola mundo.",
                provider="openai",
                model="gpt-4o",
            )
            await session.commit()

            assert segment.qa_score == report.overall_score
            assert segment.qa_status == report.status
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_segment_fields_rollback_to_previous_state() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            _, _, segment = await _seed_book_chapter_segment(session)
            segment.qa_score = 25
            segment.qa_status = "failed"
            await session.commit()

            previous_score = segment.qa_score
            previous_status = segment.qa_status

            try:
                report = TranslationQualityReport(
                    segment_id=segment.id,
                    evaluator_version="1.0.0",
                    mode="deterministic",
                    deterministic_score=90,
                    overall_score=90,
                    status="passed",
                    summary="good",
                    source_checksum=sha256_text("Hello world."),
                    translated_checksum=sha256_text("Hola mundo."),
                    issues=[{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}],
                )
                session.add(report)
                segment.qa_score = 90
                segment.qa_status = "passed"
                await session.flush()
                raise RuntimeError("forced rollback")
            except RuntimeError:
                await session.rollback()

            assert segment.qa_score == previous_score
            assert segment.qa_status == previous_status
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_book_quality_summary_aggregates_scores_and_stale_reports() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await _cleanup_quality_tables(session)
            book, chapter, segment_a = await _seed_book_chapter_segment(session, book_title="Summary book", segment_number=1)
            _, _, segment_b = await _seed_book_chapter_segment(session, book_title="Summary book", segment_number=2)
            _, _, segment_c = await _seed_book_chapter_segment(session, book_title="Summary book", segment_number=3)

            segment_a.chapter_id = chapter.id
            segment_b.chapter_id = chapter.id
            segment_c.chapter_id = chapter.id

            await session.execute(
                text("UPDATE segments SET original_text = :source, translated_text = :translated WHERE id = :segment_id"),
                {"source": "Alpha.", "translated": "Álpha.", "segment_id": segment_a.id},
            )
            await session.execute(
                text("UPDATE segments SET original_text = :source, translated_text = :translated WHERE id = :segment_id"),
                {"source": "Beta.", "translated": "Béta.", "segment_id": segment_b.id},
            )
            await session.execute(
                text("UPDATE segments SET original_text = :source, translated_text = :translated WHERE id = :segment_id"),
                {"source": "Gamma.", "translated": "Gama.", "segment_id": segment_c.id},
            )

            await session.commit()

            report_a = TranslationQualityReport(
                segment_id=segment_a.id,
                evaluator_version="1.0.0",
                mode="deterministic",
                deterministic_score=95,
                overall_score=95,
                status="passed",
                summary="ok",
                source_checksum=sha256_text("Alpha."),
                translated_checksum=sha256_text("Álpha."),
                issues=[{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}],
            )
            report_b = TranslationQualityReport(
                segment_id=segment_b.id,
                evaluator_version="1.0.0",
                mode="deterministic",
                deterministic_score=60,
                overall_score=60,
                status="needs_review",
                summary="review",
                source_checksum=sha256_text("Beta."),
                translated_checksum=sha256_text("Béta."),
                issues=[{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}],
            )
            report_c = TranslationQualityReport(
                segment_id=segment_c.id,
                evaluator_version="1.0.0",
                mode="deterministic",
                deterministic_score=30,
                overall_score=30,
                status="failed",
                summary="bad",
                source_checksum=sha256_text("Gamma."),
                translated_checksum=sha256_text("Gama."),
                issues=[{"code": "ok", "severity": "info", "message": "ok", "field": "translation", "score_impact": 0}],
            )
            session.add_all([report_a, report_b, report_c])
            await session.commit()

            # Mark the first report as stale by changing the live translated_text.
            await session.execute(
                text("UPDATE segments SET translated_text = :translated WHERE id = :segment_id"),
                {"translated": "Nueva traducción", "segment_id": segment_a.id},
            )
            await session.commit()

            summary = await QualityAssuranceService(session).get_book_summary(book.id)
            assert summary.checked_segments == 3
            assert summary.passed == 1
            assert summary.needs_review == 1
            assert summary.failed == 1
            assert summary.stale_reports == 1
            assert summary.average_score == 61.666666666666664
    finally:
        await engine.dispose()
