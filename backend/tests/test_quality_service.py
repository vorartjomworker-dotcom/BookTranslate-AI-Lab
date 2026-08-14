from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ValidationError
from app.models import Book, Chapter, Segment, TranslationJob
from app.quality.ai_evaluator import QualityEvaluationError
from app.quality.service import QualityAssuranceService, QualityIssue


@pytest.mark.asyncio
async def test_quality_service_creates_deterministic_report(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=1,
            original_text="Hello world from the book.",
            translated_text="Hola mundo del libro.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        service = QualityAssuranceService(session)
        report = await service.evaluate_segment(
            segment_id=segment.id,
            source_text="Hello world from the book.",
            translated_text="Hola mundo del libro.",
            provider="openai",
            model="gpt-4o",
            mode="deterministic",
        )

        assert report.segment_id == segment.id
        assert report.mode == "deterministic"
        assert report.ai_score is None
        assert 0 <= report.deterministic_score <= 100
        assert report.overall_score == report.deterministic_score
        assert report.status in {"passed", "needs_review", "failed"}
        assert isinstance(report.issues, list)
        assert segment.qa_score == report.overall_score
        assert segment.qa_status == report.status


@pytest.mark.asyncio
async def test_quality_service_creates_full_report_and_persists_scores(async_session_factory, monkeypatch):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=2,
            original_text="Use the same API token.",
            translated_text="Usa el mismo token de API.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        class FakeAI:
            async def evaluate(self, **kwargs):
                return [
                    QualityIssue(
                        code="ai_issue",
                        severity="warning",
                        message="AI content warning",
                        field="translated_text",
                        score_impact=15,
                    )
                ]

        monkeypatch.setattr("app.quality.service.settings.quality_ai_enabled", True, raising=False)
        service = QualityAssuranceService(session, ai_evaluator=FakeAI())
        report = await service.evaluate_segment(
            segment_id=segment.id,
            source_text="Use the same API token.",
            translated_text="Usa el mismo token de API.",
            provider="openai",
            model="gpt-4o",
            mode="full",
        )

        assert report.mode == "full"
        assert report.deterministic_score == 100
        assert report.ai_score == 85
        assert report.overall_score == 97
        assert report.status == "passed"
        assert any(issue.get("code") == "ai_issue" for issue in report.issues)


@pytest.mark.asyncio
async def test_quality_service_is_idempotent_for_job_and_evaluator_version(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=3,
            original_text="This is a final check.",
            translated_text="Esta es una comprobación final.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        job = TranslationJob(
            segment_id=segment.id,
            provider="openai",
            model="gpt-4o",
            status="completed",
            attempt=1,
            max_attempts=3,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        service = QualityAssuranceService(session)
        first = await service.evaluate_for_job(
            job_id=job.id,
            source_text="This is a final check.",
            translated_text="Esta es una comprobación final.",
            provider="openai",
            model="gpt-4o",
        )
        second = await service.evaluate_for_job(
            job_id=job.id,
            source_text="This is a final check.",
            translated_text="Esta es una comprobación final.",
            provider="openai",
            model="gpt-4o",
        )

        assert first.id == second.id
        assert first.translation_job_id == job.id
        assert first.evaluator_version == service.config.evaluator_version


@pytest.mark.asyncio
async def test_quality_service_does_not_create_second_report_for_duplicate_job_processing(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=4,
            original_text="Duplicate job check.",
            translated_text="Comprobación de trabajo duplicado.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        job = TranslationJob(
            segment_id=segment.id,
            provider="openai",
            model="gpt-4o",
            status="completed",
            attempt=1,
            max_attempts=3,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        service = QualityAssuranceService(session)
        first = await service.evaluate_for_job(
            job_id=job.id,
            source_text="Duplicate job check.",
            translated_text="Comprobación de trabajo duplicado.",
        )
        second = await service.evaluate_for_job(
            job_id=job.id,
            source_text="Duplicate job check.",
            translated_text="Comprobación de trabajo duplicado.",
        )

        assert first.id == second.id
        assert (await service.repository.get_by_job_and_version(job.id, service.config.evaluator_version)).id == first.id


@pytest.mark.asyncio
async def test_quality_service_creates_distinct_reports_for_different_jobs_same_segment(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=5,
            original_text="Shared segment.",
            translated_text="Segmento compartido.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        first_job = TranslationJob(
            segment_id=segment.id,
            provider="openai",
            model="gpt-4o",
            status="completed",
            attempt=1,
            max_attempts=3,
        )
        second_job = TranslationJob(
            segment_id=segment.id,
            provider="openai",
            model="gpt-4o",
            status="completed",
            attempt=1,
            max_attempts=3,
        )
        session.add_all([first_job, second_job])
        await session.commit()
        await session.refresh(first_job)
        await session.refresh(second_job)

        service = QualityAssuranceService(session)
        first_report = await service.evaluate_for_job(
            job_id=first_job.id,
            source_text="Shared segment.",
            translated_text="Segmento compartido.",
        )
        second_report = await service.evaluate_for_job(
            job_id=second_job.id,
            source_text="Shared segment.",
            translated_text="Segmento compartido.",
        )

        assert first_report.id != second_report.id
        assert first_report.translation_job_id == first_job.id
        assert second_report.translation_job_id == second_job.id


@pytest.mark.asyncio
async def test_quality_service_reuses_existing_manual_report_for_same_checksum(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=6,
            original_text="Manual QA identity.",
            translated_text="Identidad de QA manual.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        service = QualityAssuranceService(session)
        first = await service.evaluate_segment(
            segment_id=segment.id,
            source_text="Manual QA identity.",
            translated_text="Identidad de QA manual.",
            mode="deterministic",
        )
        second = await service.evaluate_segment(
            segment_id=segment.id,
            source_text="Manual QA identity.",
            translated_text="Identidad de QA manual.",
            mode="deterministic",
        )

        assert first.id == second.id
        assert first.translation_job_id is None


@pytest.mark.asyncio
async def test_quality_service_creates_new_manual_report_when_source_checksum_changes(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=7,
            original_text="Source one.",
            translated_text="Traducción uno.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        service = QualityAssuranceService(session)
        first = await service.evaluate_segment(
            segment_id=segment.id,
            source_text="Source one.",
            translated_text="Traducción uno.",
        )
        second = await service.evaluate_segment(
            segment_id=segment.id,
            source_text="Source two.",
            translated_text="Traducción uno.",
        )

        assert first.id != second.id
        assert first.translation_job_id is None
        assert second.translation_job_id is None


@pytest.mark.asyncio
async def test_quality_service_creates_new_manual_report_when_translated_checksum_changes(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=8,
            original_text="A sentence needs checking.",
            translated_text="Una frase necesita revisión.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        service = QualityAssuranceService(session)
        first = await service.evaluate_segment(
            segment_id=segment.id,
            source_text="A sentence needs checking.",
            translated_text="Una frase necesita revisión.",
        )
        second = await service.evaluate_segment(
            segment_id=segment.id,
            source_text="A sentence needs checking.",
            translated_text="Una frase necesita revisión actualizada.",
        )

        assert first.id != second.id
        assert first.translation_job_id is None
        assert second.translation_job_id is None


@pytest.mark.asyncio
async def test_quality_service_get_book_summary_marks_stale_reports(async_session_factory):
    async with async_session_factory() as session:
        book = Book(title="QA book", author="Tester", file_path="/tmp/book.pdf", file_type="pdf", language="en")
        chapter = Chapter(book=book, chapter_number=1, title="Intro", content="Text", status="translated")
        segment = Segment(
            chapter=chapter,
            segment_number=1,
            original_text="Original text.",
            translated_text="Versión actual.",
            status="translated",
        )
        session.add_all([book, chapter, segment])
        await session.commit()
        await session.refresh(book)
        await session.refresh(chapter)
        await session.refresh(segment)

        service = QualityAssuranceService(session)
        report = await service.evaluate_segment(
            segment_id=segment.id,
            source_text="Original text.",
            translated_text="Versión actual.",
        )
        segment.translated_text = "Versión nueva"
        await session.flush()

        summary = await service.get_book_summary(book.id)
        assert summary.total_segments == 1
        assert summary.checked_segments == 1
        assert summary.stale_reports == 1
        assert report.overall_score >= 0


@pytest.mark.asyncio
async def test_quality_service_syncs_segment_legacy_fields(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=10,
            original_text="Legacy sync.",
            translated_text="Sincronización heredada.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        service = QualityAssuranceService(session)
        report = await service.evaluate_segment(
            segment_id=segment.id,
            source_text="Legacy sync.",
            translated_text="Sincronización heredada.",
        )

        assert segment.qa_score == report.overall_score
        assert segment.qa_status == report.status
        assert segment.qa_comment == report.summary


@pytest.mark.asyncio
async def test_quality_service_skips_ai_in_deterministic_mode(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=11,
            original_text="No AI fallback.",
            translated_text="Sin IA.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        ai = AsyncMock()
        service = QualityAssuranceService(session, ai_evaluator=ai)
        await service.evaluate_segment(
            segment_id=segment.id,
            source_text="No AI fallback.",
            translated_text="Sin IA.",
            mode="deterministic",
        )

        ai.evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_quality_service_calls_ai_once_in_full_mode(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=12,
            original_text="Ask the AI.",
            translated_text="Pregúntale a la IA.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        ai = AsyncMock()
        ai.evaluate.return_value = [
            QualityIssue(
                code="ai_issue",
                severity="warning",
                message="AI warning",
                field="translated_text",
                score_impact=10,
            )
        ]

        service = QualityAssuranceService(session, ai_evaluator=ai)
        await service.evaluate_segment(
            segment_id=segment.id,
            source_text="Ask the AI.",
            translated_text="Pregúntale a la IA.",
            mode="full",
        )

        ai.evaluate.assert_awaited_once()


@pytest.mark.asyncio
async def test_quality_service_keeps_deterministic_result_when_ai_evaluator_errors(async_session_factory, monkeypatch):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=13,
            original_text="AI error test.",
            translated_text="Prueba de error de IA.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        class ExplodingAI:
            async def evaluate(self, **kwargs):
                raise QualityEvaluationError("AI failed", code="quality_ai_provider_error")

        monkeypatch.setattr("app.quality.service.settings.quality_ai_enabled", True, raising=False)
        service = QualityAssuranceService(session, ai_evaluator=ExplodingAI())
        report = await service.evaluate_segment(
            segment_id=segment.id,
            source_text="AI error test.",
            translated_text="Prueba de error de IA.",
            mode="full",
        )

        assert report.evaluator_error_code == "quality_ai_provider_error"
        assert report.deterministic_score == report.overall_score
        assert report.ai_score is None
        assert any(issue.get("code") == "quality_ai_evaluation_error" for issue in report.issues)


@pytest.mark.asyncio
async def test_quality_service_does_not_hide_repository_persistence_errors(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=14,
            original_text="Persistence issue.",
            translated_text="Problema de persistencia.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        service = QualityAssuranceService(session)
        service.repository = type("Repo", (), {"save": AsyncMock(side_effect=RuntimeError("boom"))})()

        with pytest.raises(RuntimeError, match="boom"):
            await service.evaluate_segment(
                segment_id=segment.id,
                source_text="Persistence issue.",
                translated_text="Problema de persistencia.",
            )


@pytest.mark.asyncio
async def test_quality_service_rolls_back_legacy_updates_on_persistence_failure(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=15,
            original_text="Rollback check.",
            translated_text="Comprobación de rollback.",
            status="translated",
            qa_score=11,
            qa_status="pending",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        original_score = segment.qa_score
        original_status = segment.qa_status

        service = QualityAssuranceService(session)
        service.repository = type("Repo", (), {"save": AsyncMock(side_effect=RuntimeError("db write failed"))})()

        with pytest.raises(RuntimeError, match="db write failed"):
            await service.evaluate_segment(
                segment_id=segment.id,
                source_text="Rollback check.",
                translated_text="Comprobación de rollback.",
            )

        await session.rollback()
        await session.refresh(segment)
        assert segment.qa_score == original_score
        assert segment.qa_status == original_status


@pytest.mark.asyncio
async def test_quality_service_rejects_empty_translation(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=16,
            original_text="A text.",
            translated_text="",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        service = QualityAssuranceService(session)
        with pytest.raises(ValidationError, match="translated text"):
            await service.evaluate_segment(
                segment_id=segment.id,
                source_text="A text.",
                translated_text="",
            )
