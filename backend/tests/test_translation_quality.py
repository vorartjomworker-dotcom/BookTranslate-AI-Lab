from __future__ import annotations

import pytest

from app.main import app
from app.models import Segment, TranslationJob
from app.quality.service import QualityAssuranceService, QualityIssue


def test_quality_routes_are_present_in_openapi():
    schema = app.openapi()
    paths = set(schema.get("paths", {}))
    assert "/api/v1/segments/{segment_id}/quality" in paths
    assert "/api/v1/translation-jobs/{job_id}/quality" in paths


@pytest.mark.asyncio
async def test_translation_quality_report_scores_and_updates_legacy_fields(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=1,
            original_text="Hello world from the book.",
            translated_text="Привет мир из книги.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        service = QualityAssuranceService(session)
        report = await service.evaluate_segment(
            segment_id=segment.id,
            translated_text="Привет мир из книги.",
            source_text="Hello world from the book.",
            provider="openai",
            model="gpt-4o",
        )

        assert report.score >= 0
        assert report.score <= 100
        assert report.status in {"passed", "failed"}
        assert segment.qa_score == report.score
        assert segment.qa_status == report.status
        assert segment.qa_comment == report.summary


@pytest.mark.asyncio
async def test_translation_quality_report_is_idempotent_for_same_job(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=2,
            original_text="This is a test sentence.",
            translated_text="Это проверочное предложение.",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        job = TranslationJob(
            segment_id=segment.id,
            provider="openai",
            model="gpt-4o",
            status="running",
            attempt=1,
            max_attempts=3,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        service = QualityAssuranceService(session)
        first = await service.evaluate_for_job(
            job_id=job.id,
            source_text="This is a test sentence.",
            translated_text="Это проверочное предложение.",
            provider="openai",
            model="gpt-4o",
        )
        second = await service.evaluate_for_job(
            job_id=job.id,
            source_text="This is a test sentence.",
            translated_text="Это проверочное предложение.",
            provider="openai",
            model="gpt-4o",
        )

        assert first.id == second.id
        assert first.translation_job_id == job.id
        assert first.segment_id == segment.id


@pytest.mark.asyncio
async def test_translation_quality_service_applies_ai_evaluator_when_enabled(async_session_factory, monkeypatch):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=3,
            original_text="hello world",
            translated_text="hola mundo",
            status="translated",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        monkeypatch.setattr("app.quality.service.settings.quality_ai_enabled", True)

        class FakeAI:
            async def evaluate(self, **kwargs):
                return [
                    QualityIssue(
                        code="ai_issue",
                        severity="warning",
                        message="AI quality warning",
                        field="translated_text",
                        score_impact=15,
                    )
                ]

        service = QualityAssuranceService(session, ai_evaluator=FakeAI())
        report = await service.evaluate_segment(
            segment_id=segment.id,
            source_text="hello world",
            translated_text="hola mundo",
            provider="openai",
            model="gpt-4o",
            mode="full",
        )

        assert report.deterministic_score == 100
        assert report.ai_score == 85
        assert report.overall_score == 97
        assert any(issue.get("code") == "ai_issue" for issue in report.issues)
        assert segment.qa_score == report.overall_score
