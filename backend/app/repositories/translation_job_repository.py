from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.translation_job import TranslationJob


class TranslationJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, job_id: int) -> TranslationJob | None:
        return await self.session.get(TranslationJob, job_id)

    async def list_for_segment(self, segment_id: int, *, limit: int = 50, offset: int = 0) -> list[TranslationJob]:
        stmt = (
            select(TranslationJob)
            .where(TranslationJob.segment_id == segment_id)
            .order_by(TranslationJob.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_for_segment(self, segment_id: int) -> TranslationJob | None:
        stmt = select(TranslationJob).where(
            TranslationJob.segment_id == segment_id,
            TranslationJob.status.in_(["pending_enqueue", "queued", "running"]),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(self, **values: object) -> TranslationJob:
        job = TranslationJob(**values)
        self.session.add(job)
        await self.session.flush()
        return job

    async def update_status(self, job: TranslationJob, *, status: str, **extra_fields: object) -> TranslationJob:
        job.status = status
        for field_name, value in extra_fields.items():
            if value is not None:
                setattr(job, field_name, value)
        if status == "running":
            job.started_at = job.started_at or datetime.utcnow()
        if status == "completed":
            job.completed_at = job.completed_at or datetime.utcnow()
        if status == "failed":
            job.failed_at = job.failed_at or datetime.utcnow()
        await self.session.flush()
        return job

    async def create_retry(self, original_job: TranslationJob, *, segment_id: int, provider: str, model: str | None, max_attempts: int) -> TranslationJob:
        retry_job = TranslationJob(
            segment_id=segment_id,
            provider=provider,
            model=model,
            status="pending_enqueue",
            attempt=0,
            max_attempts=max_attempts,
            retry_of_id=original_job.id,
        )
        self.session.add(retry_job)
        await self.session.flush()
        return retry_job
