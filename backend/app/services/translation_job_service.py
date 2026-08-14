from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models import Segment, TranslationJob
from app.repositories.translation_job_repository import TranslationJobRepository


class TranslationJobService:
    def __init__(self, session) -> None:
        self.session = session
        self.repository = TranslationJobRepository(session)

    async def get_job(self, job_id: int) -> TranslationJob:
        job = await self.repository.get_by_id(job_id)
        if job is None:
            raise NotFoundError("translation job", job_id)
        return job

    async def list_jobs_for_segment(self, segment_id: int, *, limit: int = 50, offset: int = 0) -> list[TranslationJob]:
        segment = await self.session.get(Segment, segment_id)
        if segment is None:
            raise NotFoundError("segment", segment_id)
        return await self.repository.list_for_segment(segment_id, limit=limit, offset=offset)

    async def create_job_for_segment(
        self,
        segment_id: int,
        *,
        provider: str | None = None,
        model: str | None = None,
        max_attempts: int | None = None,
    ) -> TranslationJob:
        segment = await self.session.get(Segment, segment_id)
        if segment is None:
            raise NotFoundError("segment", segment_id)

        existing = await self.repository.get_active_for_segment(segment_id)
        if existing is not None:
            raise ConflictError(
                "An active translation job already exists for this segment.",
                details={"segment_id": segment_id, "job_id": existing.id},
            )

        job = TranslationJob(
            segment_id=segment_id,
            provider=(provider or settings.default_ai_provider).strip() or settings.default_ai_provider,
            model=model,
            status="pending_enqueue",
            attempt=0,
            max_attempts=int(max_attempts or settings.translation_job_retry_limit),
        )
        self.session.add(job)
        try:
            await self.session.commit()
            await self.session.refresh(job)
            return job
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Translation job creation conflicts with an active job for this segment.", details={"segment_id": segment_id}) from exc

    async def retry_failed_job(self, job_id: int, *, provider: str | None = None, model: str | None = None) -> TranslationJob:
        job = await self.get_job(job_id)
        if job.status != "failed":
            raise ConflictError("Only failed jobs can be retried.", details={"job_id": job_id, "status": job.status})

        retry = TranslationJob(
            segment_id=job.segment_id,
            provider=(provider or job.provider or settings.default_ai_provider).strip() or settings.default_ai_provider,
            model=model or job.model,
            status="pending_enqueue",
            attempt=0,
            max_attempts=max(1, int(job.max_attempts or settings.translation_job_retry_limit)),
            retry_of_id=job.id,
        )
        self.session.add(retry)
        try:
            await self.session.commit()
            await self.session.refresh(retry)
            return retry
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Retry job creation conflicts with an active job for this segment.", details={"segment_id": job.segment_id, "job_id": job.id}) from exc

    async def get_active_job_for_segment(self, segment_id: int) -> TranslationJob | None:
        stmt = select(TranslationJob).where(
            TranslationJob.segment_id == segment_id,
            TranslationJob.status.in_(["pending_enqueue", "queued", "running"]),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
