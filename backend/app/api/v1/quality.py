from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.dependencies.db import get_db
from app.models import TranslationJob
from app.quality.ai_evaluator import AIQualityEvaluator, NullQualityAIEvaluator
from app.quality.service import QualityAssuranceService
from app.schemas.quality import BookQualitySummaryRead, QualityCheckRequest, TranslationQualityReportRead

router = APIRouter(prefix="/api/v1", tags=["quality"])


def _build_service(db: AsyncSession, *, mode: str) -> QualityAssuranceService:
    from app.core.config import settings

    evaluator = AIQualityEvaluator() if (mode == "full" and settings.quality_ai_enabled) else NullQualityAIEvaluator()
    return QualityAssuranceService(db, ai_evaluator=evaluator)


@router.get("/quality-reports/{report_id}", response_model=TranslationQualityReportRead)
async def get_quality_report(report_id: int, db: AsyncSession = Depends(get_db)) -> TranslationQualityReportRead:
    service = QualityAssuranceService(db)
    report = await service.repository.get_by_id(report_id)
    if report is None:
        raise NotFoundError("quality report", report_id)
    return TranslationQualityReportRead.model_validate(report)


@router.get("/segments/{segment_id}/quality-report", response_model=TranslationQualityReportRead)
async def get_segment_quality_report(segment_id: int, db: AsyncSession = Depends(get_db)) -> TranslationQualityReportRead:
    service = QualityAssuranceService(db)
    report = await service.repository.get_latest_by_segment(segment_id)
    if report is None:
        raise NotFoundError("quality report", segment_id)
    return TranslationQualityReportRead.model_validate(report)


@router.get("/books/{book_id}/quality-summary", response_model=BookQualitySummaryRead)
async def get_book_quality_summary(book_id: int, db: AsyncSession = Depends(get_db)) -> BookQualitySummaryRead:
    service = QualityAssuranceService(db)
    summary = await service.get_book_summary(book_id)
    return BookQualitySummaryRead.model_validate(summary, from_attributes=True)


@router.post(
    "/segments/{segment_id}/quality-check",
    response_model=TranslationQualityReportRead,
    status_code=status.HTTP_200_OK,
)
async def check_segment_quality(
    segment_id: int,
    payload: QualityCheckRequest,
    db: AsyncSession = Depends(get_db),
) -> TranslationQualityReportRead:
    service = _build_service(db, mode=payload.mode)
    report = await service.evaluate_segment(segment_id, mode=payload.mode)
    await db.commit()
    return TranslationQualityReportRead.model_validate(report)


# --- Deprecated aliases (thin, no business logic of their own) -------------------------------


@router.get(
    "/segments/{segment_id}/quality",
    response_model=TranslationQualityReportRead,
    deprecated=True,
    include_in_schema=True,
)
async def get_segment_quality_legacy(segment_id: int, db: AsyncSession = Depends(get_db)) -> TranslationQualityReportRead:
    """Deprecated alias for GET /segments/{segment_id}/quality-report."""
    return await get_segment_quality_report(segment_id, db)


@router.post(
    "/translation-jobs/{job_id}/quality",
    response_model=TranslationQualityReportRead,
    status_code=status.HTTP_200_OK,
    deprecated=True,
    include_in_schema=True,
)
async def create_quality_report_for_job_legacy(
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> TranslationQualityReportRead:
    """Deprecated alias: resolves the job's segment and delegates to the quality-check endpoint."""
    job = await db.get(TranslationJob, job_id)
    if job is None:
        raise NotFoundError("translation job", job_id)
    return await check_segment_quality(job.segment_id, QualityCheckRequest(mode="deterministic"), db)

