from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.dependencies.db import get_db
from app.models import Segment, TranslationJob
from app.schemas.translation_job import TranslationJobCreate, TranslationJobRead

router = APIRouter(prefix="/api/v1", tags=["translation-jobs"])


@router.get("/segments/{segment_id}/translation-jobs", response_model=list[TranslationJobRead])
async def list_translation_jobs_for_segment(
    segment_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[TranslationJobRead]:
    segment = await db.get(Segment, segment_id)
    if segment is None:
        raise NotFoundError("segment", segment_id)

    stmt = (
        select(TranslationJob)
        .where(TranslationJob.segment_id == segment_id)
        .order_by(TranslationJob.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return [TranslationJobRead.model_validate(job) for job in jobs]


@router.post(
    "/segments/{segment_id}/translation-jobs",
    response_model=TranslationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_translation_job_for_segment(
    segment_id: int,
    payload: TranslationJobCreate | None = None,
    db: AsyncSession = Depends(get_db),
) -> TranslationJobRead:
    segment = await db.get(Segment, segment_id)
    if segment is None:
        raise NotFoundError("segment", segment_id)

    active_job = await db.execute(
        select(TranslationJob).where(
            TranslationJob.segment_id == segment_id,
            TranslationJob.status.in_(["pending_enqueue", "queued", "running"]),
        )
    )
    if active_job.scalar_one_or_none() is not None:
        raise ConflictError(
            "An active translation job already exists for this segment.",
            details={"segment_id": segment_id},
        )

    job_payload = payload.model_dump(exclude_none=True) if payload is not None else {}
    provider = (job_payload.get("provider") or settings.default_ai_provider).strip() or settings.default_ai_provider
    model = job_payload.get("model")
    max_attempts = int(job_payload.get("max_attempts") or settings.translation_job_retry_limit)

    job = TranslationJob(
        segment_id=segment_id,
        provider=provider,
        model=model,
        status="pending_enqueue",
        attempt=0,
        max_attempts=max_attempts,
    )

    db.add(job)
    await db.commit()
    await db.refresh(job)
    return TranslationJobRead.model_validate(job)


@router.get("/translation-jobs/{job_id}", response_model=TranslationJobRead)
async def get_translation_job(job_id: int, db: AsyncSession = Depends(get_db)) -> TranslationJobRead:
    job = await db.get(TranslationJob, job_id)
    if job is None:
        raise NotFoundError("translation job", job_id)
    return TranslationJobRead.model_validate(job)


@router.post(
    "/translation-jobs/{job_id}/retry",
    response_model=TranslationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_translation_job(job_id: int, db: AsyncSession = Depends(get_db)) -> TranslationJobRead:
    job = await db.get(TranslationJob, job_id)
    if job is None:
        raise NotFoundError("translation job", job_id)
    if job.status != "failed":
        raise ConflictError("Only failed jobs can be retried.", details={"job_id": job_id, "status": job.status})

    retry = TranslationJob(
        segment_id=job.segment_id,
        provider=job.provider,
        model=job.model,
        status="pending_enqueue",
        attempt=0,
        max_attempts=max(1, int(job.max_attempts or settings.translation_job_retry_limit)),
        retry_of_id=job.id,
    )
    db.add(retry)
    await db.commit()
    await db.refresh(retry)
    return TranslationJobRead.model_validate(retry)
