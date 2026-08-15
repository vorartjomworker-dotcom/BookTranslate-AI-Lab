from __future__ import annotations

from typing import Literal, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.models import Book, Chapter, Segment, TranslationJob, TranslationQualityReport
from app.quality.ai_evaluator import NullQualityAIEvaluator, QualityEvaluationError
from app.quality.config import QualityConfig, build_quality_config
from app.quality.deterministic import DeterministicQualityEvaluator, QualityIssue, QualityStatus, sha256_text
from app.quality.repository import QualityAssuranceRepository

QualityMode = Literal["deterministic", "full"]

_STATUS_RANK = {"passed": 0, "needs_review": 1, "failed": 2}


class QualityAIEvaluator(Protocol):
    async def evaluate(
        self,
        *,
        source_text: str,
        translated_text: str,
        source_language: str | None = None,
        target_language: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> list[QualityIssue]:
        ...


class BookQualitySummary:
    __slots__ = (
        "book_id",
        "total_segments",
        "translated_segments",
        "checked_segments",
        "passed",
        "needs_review",
        "failed",
        "stale_reports",
        "average_score",
    )

    def __init__(
        self,
        *,
        book_id: int,
        total_segments: int,
        translated_segments: int,
        checked_segments: int,
        passed: int,
        needs_review: int,
        failed: int,
        stale_reports: int,
        average_score: float | None,
    ) -> None:
        self.book_id = book_id
        self.total_segments = total_segments
        self.translated_segments = translated_segments
        self.checked_segments = checked_segments
        self.passed = passed
        self.needs_review = needs_review
        self.failed = failed
        self.stale_reports = stale_reports
        self.average_score = average_score


class QualityAssuranceService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        ai_evaluator: QualityAIEvaluator | None = None,
        deterministic_evaluator: DeterministicQualityEvaluator | None = None,
        config: QualityConfig | None = None,
    ) -> None:
        self.session = session
        self.config = config or build_quality_config()
        self.repository = QualityAssuranceRepository(session)
        self.ai_evaluator = ai_evaluator or NullQualityAIEvaluator()
        self.deterministic_evaluator = deterministic_evaluator or DeterministicQualityEvaluator(self.config)

    async def evaluate_segment(
        self,
        segment_id: int,
        *,
        source_text: str | None = None,
        translated_text: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        source_language: str | None = None,
        target_language: str | None = None,
        translation_job_id: int | None = None,
        mode: QualityMode = "deterministic",
        force: bool = False,
    ) -> TranslationQualityReport:
        segment = await self.session.get(Segment, segment_id)
        if segment is None:
            raise NotFoundError("segment", segment_id)

        source_text = source_text if source_text is not None else segment.original_text
        translated_text = translated_text if translated_text is not None else (segment.translated_text or "")
        if not (translated_text or "").strip():
            raise ValidationError("Segment has no translated text to evaluate.", details={"segment_id": segment_id})

        provider = provider or segment.model_used or settings.default_ai_provider
        model = model or segment.model_used or settings.default_ai_model
        source_language = source_language or settings.default_source_language
        target_language = target_language or settings.default_target_language

        source_checksum = sha256_text(source_text)
        translated_checksum = sha256_text(translated_text)
        evaluator_version = self.config.evaluator_version

        get_by_job = getattr(self.repository, "get_by_job_and_version", None)
        get_by_segment = getattr(self.repository, "get_by_segment_and_version", None)

        existing_report = None
        if translation_job_id is not None and callable(get_by_job):
            existing_report = await get_by_job(translation_job_id, evaluator_version)
        elif callable(get_by_segment):
            existing_report = await get_by_segment(segment_id, evaluator_version)

        if existing_report is not None and not force:
            same_payload = (
                existing_report.mode == mode
                and existing_report.source_checksum == source_checksum
                and existing_report.translated_checksum == translated_checksum
            )
            if same_payload:
                self._sync_legacy_fields(segment, existing_report)
                return existing_report
            if translation_job_id is None:
                existing_report = None

        deterministic_score, issues = self.deterministic_evaluator.evaluate(
            source_text=source_text,
            translated_text=translated_text,
            source_language=source_language,
            target_language=target_language,
            provider=provider,
            model=model,
        )
        ai_score: int | None = None
        overall_score = deterministic_score
        evaluator_error_code: str | None = None
        status: QualityStatus = self._score_to_status(overall_score)

        full_mode_ai_enabled = mode == "full" and (
            settings.quality_ai_enabled or not isinstance(self.ai_evaluator, NullQualityAIEvaluator)
        )
        if full_mode_ai_enabled:
            try:
                ai_issues = await self.ai_evaluator.evaluate(
                    source_text=source_text,
                    translated_text=translated_text,
                    source_language=source_language,
                    target_language=target_language,
                    provider=provider,
                    model=model,
                )
                ai_score = max(0, min(100, 100 - sum(issue.score_impact for issue in ai_issues)))
                if ai_issues:
                    issues = [*issues, *ai_issues]
                overall_score = int(
                    round(
                        (self.config.deterministic_weight * deterministic_score)
                        + (self.config.ai_weight * ai_score)
                    )
                )
                status = self._score_to_status(overall_score)
            except QualityEvaluationError as exc:
                evaluator_error_code = exc.code
                issues = [
                    *issues,
                    QualityIssue(
                        code="quality_ai_evaluation_error",
                        severity="warning",
                        message="AI quality evaluation failed; deterministic result was retained.",
                        field="ai_evaluator",
                        score_impact=0,
                    ),
                ]
                overall_score = deterministic_score
                status = "needs_review"

        summary = self._build_summary(issues)

        if existing_report is None:
            report = TranslationQualityReport(
                segment_id=segment_id,
                translation_job_id=translation_job_id,
                evaluator_version=evaluator_version,
                mode=mode,
                deterministic_score=deterministic_score,
                ai_score=ai_score,
                overall_score=overall_score,
                evaluator_error_code=evaluator_error_code,
                status=status,
                summary=summary,
                provider=provider,
                model=model,
                source_language=source_language,
                target_language=target_language,
                source_checksum=source_checksum,
                translated_checksum=translated_checksum,
                issues=[issue.model_dump(mode="json") for issue in issues],
            )
        else:
            report = existing_report
            report.translation_job_id = translation_job_id if translation_job_id is not None else report.translation_job_id
            report.mode = mode
            report.deterministic_score = deterministic_score
            report.ai_score = ai_score
            report.overall_score = overall_score
            report.evaluator_error_code = evaluator_error_code
            report.status = status
            report.summary = summary
            report.provider = provider
            report.model = model
            report.source_language = source_language
            report.target_language = target_language
            report.source_checksum = source_checksum
            report.translated_checksum = translated_checksum
            report.issues = [issue.model_dump(mode="json") for issue in issues]

        try:
            await self.repository.save(report)
            self._sync_legacy_fields(segment, report)
            await self.session.flush()
        except Exception:
            await self.session.rollback()
            raise
        return report

    async def evaluate_for_job(
        self,
        job_id: int,
        *,
        source_text: str | None = None,
        translated_text: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        source_language: str | None = None,
        target_language: str | None = None,
        mode: QualityMode = "deterministic",
        force: bool = False,
    ) -> TranslationQualityReport:
        job = await self.session.get(TranslationJob, job_id)
        if job is None:
            raise NotFoundError("translation job", job_id)
        return await self.evaluate_segment(
            job.segment_id,
            source_text=source_text,
            translated_text=translated_text,
            provider=provider or job.provider,
            model=model or job.model,
            source_language=source_language,
            target_language=target_language,
            translation_job_id=job.id,
            mode=mode,
            force=force,
        )

    async def get_latest_report_for_segment(self, segment_id: int) -> TranslationQualityReport | None:
        segment = await self.session.get(Segment, segment_id)
        if segment is None:
            return None
        if segment.qa_status == "stale":
            return None

        report = await self.repository.get_latest_by_segment(segment_id)
        if report is None:
            return None

        current_source_checksum = sha256_text(segment.original_text or "")
        current_translated_checksum = sha256_text(segment.translated_text or "")
        if report.source_checksum != current_source_checksum:
            return None
        if report.translated_checksum != current_translated_checksum:
            return None
        return report

    async def get_book_summary(self, book_id: int) -> BookQualitySummary:
        book = await self.session.get(Book, book_id)
        if book is None:
            raise NotFoundError("book", book_id)

        total_stmt = (
            select(func.count(Segment.id))
            .join(Chapter, Chapter.id == Segment.chapter_id)
            .where(Chapter.book_id == book_id)
        )
        total_segments = int((await self.session.execute(total_stmt)).scalar_one() or 0)

        translated_stmt = total_stmt.where(Segment.translated_text.is_not(None), Segment.translated_text != "")
        translated_segments = int((await self.session.execute(translated_stmt)).scalar_one() or 0)

        segment_ids_stmt = (
            select(Segment.id, Segment.original_text, Segment.translated_text, Segment.qa_status)
            .join(Chapter, Chapter.id == Segment.chapter_id)
            .where(Chapter.book_id == book_id)
        )
        segment_rows = (await self.session.execute(segment_ids_stmt)).all()
        segment_freshness = {
            segment_id: (
                sha256_text(original_text or ""),
                sha256_text(translated_text or ""),
                qa_status,
            )
            for segment_id, original_text, translated_text, qa_status in segment_rows
        }
        segment_ids = list(segment_freshness)

        latest_reports = await self.repository.list_latest_by_segments(segment_ids)
        stale_segment_ids = {
            segment_id
            for segment_id, report in latest_reports.items()
            if segment_id not in segment_freshness
            or segment_freshness[segment_id][2] == "stale"
            or report.source_checksum != segment_freshness[segment_id][0]
            or report.translated_checksum != segment_freshness[segment_id][1]
        }
        current_reports = {
            segment_id: report
            for segment_id, report in latest_reports.items()
            if segment_id not in stale_segment_ids
        }

        checked_segments = len(current_reports)
        passed = sum(1 for report in current_reports.values() if report.status == "passed")
        needs_review = sum(1 for report in current_reports.values() if report.status == "needs_review")
        failed = sum(1 for report in current_reports.values() if report.status == "failed")
        stale_reports = len(stale_segment_ids)
        average_score = (
            sum(report.overall_score for report in current_reports.values()) / checked_segments if checked_segments else None
        )

        return BookQualitySummary(
            book_id=book_id,
            total_segments=total_segments,
            translated_segments=translated_segments,
            checked_segments=checked_segments,
            passed=passed,
            needs_review=needs_review,
            failed=failed,
            stale_reports=stale_reports,
            average_score=average_score,
        )

    @staticmethod
    def _worse_status(a: QualityStatus, b: QualityStatus) -> QualityStatus:
        return a if _STATUS_RANK[a] >= _STATUS_RANK[b] else b

    @staticmethod
    def _build_summary(issues: list[QualityIssue]) -> str:
        if not issues:
            return "No quality issues detected."
        messages = [issue.message for issue in issues[:3]]
        if len(issues) > 3:
            messages.append(f"+{len(issues) - 3} more issues")
        return "; ".join(messages)

    def _score_to_status(self, score: int) -> QualityStatus:
        thresholds = self.config.thresholds
        if score >= thresholds.pass_threshold:
            return "passed"
        if score >= thresholds.review_threshold:
            return "needs_review"
        return "failed"

    @staticmethod
    def _sync_legacy_fields(segment: Segment, report: TranslationQualityReport) -> None:
        """Update deprecated Segment.qa_* compatibility mirrors atomically with the report."""
        segment.qa_score = int(report.overall_score)
        segment.qa_status = report.status
        segment.qa_comment = report.summary
