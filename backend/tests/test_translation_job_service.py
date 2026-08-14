from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Segment, TranslationJob
from app.services.translation_job_service import TranslationJobService


@pytest.mark.asyncio
async def test_create_job_and_list_for_segment(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=1,
            original_text="hello world",
            translated_text=None,
            status="pending",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        service = TranslationJobService(session)
        job = await service.create_job_for_segment(segment.id, provider="openai", model="gpt-4o")
        assert job.status == "pending_enqueue"
        jobs = await service.list_jobs_for_segment(segment.id)
        assert len(jobs) == 1
        assert jobs[0].id == job.id


@pytest.mark.asyncio
async def test_duplicate_active_job_is_conflict(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=2,
            original_text="hello again",
            translated_text=None,
            status="pending",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        service = TranslationJobService(session)
        await service.create_job_for_segment(segment.id, provider="openai")
        with pytest.raises(ConflictError):
            await service.create_job_for_segment(segment.id, provider="anthropic")


@pytest.mark.asyncio
async def test_retry_failed_job(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=3,
            original_text="retry me",
            translated_text=None,
            status="pending",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        service = TranslationJobService(session)
        job = TranslationJob(
            segment_id=segment.id,
            provider="openai",
            model="gpt-4o",
            status="failed",
            attempt=3,
            max_attempts=3,
            error_code="provider_quota_exceeded_error",
            error_message="quota exhausted",
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        retry = await service.retry_failed_job(job.id)
        assert retry.retry_of_id == job.id
        assert retry.status == "pending_enqueue"
