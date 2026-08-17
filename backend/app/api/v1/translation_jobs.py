from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import EDITOR_ROLES
from app.dependencies.auth import get_current_user, require_roles
from app.dependencies.db import get_db
from app.models import User
from app.schemas.translation_job import TranslationJobCreate, TranslationJobRead
from app.services.translation_job_service import TranslationJobService

router = APIRouter(prefix="/api/v1", tags=["translation-jobs"])


@router.get("/segments/{segment_id}/translation-jobs", response_model=list[TranslationJobRead])
async def list_translation_jobs_for_segment(
    segment_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[TranslationJobRead]:
    service = TranslationJobService(db)
    jobs = await service.list_jobs_for_segment(
        segment_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
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
    _: User = Depends(require_roles(*EDITOR_ROLES)),
) -> TranslationJobRead:
    job_payload = payload.model_dump(exclude_none=True) if payload is not None else {}
    job = await TranslationJobService(db).create_job_for_segment(
        segment_id,
        provider=job_payload.get("provider"),
        model=job_payload.get("model"),
        max_attempts=job_payload.get("max_attempts"),
    )
    return TranslationJobRead.model_validate(job)


@router.get("/translation-jobs/{job_id}", response_model=TranslationJobRead)
async def get_translation_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TranslationJobRead:
    job = await TranslationJobService(db).get_job(job_id)
    return TranslationJobRead.model_validate(job)


@router.post(
    "/translation-jobs/{job_id}/retry",
    response_model=TranslationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_translation_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(*EDITOR_ROLES)),
) -> TranslationJobRead:
    retry = await TranslationJobService(db).retry_failed_job(job_id)
    return TranslationJobRead.model_validate(retry)
