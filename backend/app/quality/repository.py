"""Persistence for :class:`TranslationQualityReport`.

This repository requires a real ``AsyncSession`` contract (``execute``,
``add``, ``flush``). It never silently skips persistence: if the session
cannot save a report, the underlying SQLAlchemy/database error propagates so
callers (the worker) can roll back and avoid acknowledging the job.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TranslationQualityReport


class QualityAssuranceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, report_id: int) -> TranslationQualityReport | None:
        return await self.session.get(TranslationQualityReport, report_id)

    async def get_latest_by_segment(self, segment_id: int) -> TranslationQualityReport | None:
        stmt = (
            select(TranslationQualityReport)
            .where(TranslationQualityReport.segment_id == segment_id)
            .order_by(TranslationQualityReport.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_job_and_version(self, job_id: int, evaluator_version: str) -> TranslationQualityReport | None:
        stmt = select(TranslationQualityReport).where(
            TranslationQualityReport.translation_job_id == job_id,
            TranslationQualityReport.evaluator_version == evaluator_version,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_segment_and_version(self, segment_id: int, evaluator_version: str) -> TranslationQualityReport | None:
        stmt = select(TranslationQualityReport).where(
            TranslationQualityReport.segment_id == segment_id,
            TranslationQualityReport.translation_job_id.is_(None),
            TranslationQualityReport.evaluator_version == evaluator_version,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_latest_by_segments(self, segment_ids: list[int]) -> dict[int, TranslationQualityReport]:
        if not segment_ids:
            return {}
        stmt = (
            select(TranslationQualityReport)
            .where(TranslationQualityReport.segment_id.in_(segment_ids))
            .order_by(TranslationQualityReport.segment_id, TranslationQualityReport.created_at.desc())
        )
        result = await self.session.execute(stmt)
        latest: dict[int, TranslationQualityReport] = {}
        for report in result.scalars().all():
            latest.setdefault(report.segment_id, report)
        return latest

    async def save(self, report: TranslationQualityReport) -> TranslationQualityReport:
        self.session.add(report)
        await self.session.flush()
        return report

