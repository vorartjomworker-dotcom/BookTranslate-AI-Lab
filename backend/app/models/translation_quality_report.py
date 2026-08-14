from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.base import Base

QUALITY_STATUSES: tuple[str, ...] = ("passed", "needs_review", "failed")
QUALITY_MODES: tuple[str, ...] = ("deterministic", "full")

# JSONB on PostgreSQL, plain JSON on other dialects (e.g. SQLite in unit tests).
IssuesJSON = JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


class TranslationQualityReport(Base):
    """Canonical, single source of truth for translation QA state.

    Issues are stored inline as a JSONB array of typed payloads produced by
    :class:`app.quality.deterministic.QualityIssue` / the AI evaluator; there is
    intentionally no separate quality-issues table.
    """

    __tablename__ = "translation_quality_reports"
    __table_args__ = (
        CheckConstraint(
            "deterministic_score >= 0 AND deterministic_score <= 100",
            name="ck_translation_quality_reports_deterministic_score_range",
        ),
        CheckConstraint(
            "(ai_score IS NULL) OR (ai_score >= 0 AND ai_score <= 100)",
            name="ck_translation_quality_reports_ai_score_range",
        ),
        CheckConstraint("overall_score >= 0 AND overall_score <= 100", name="ck_translation_quality_reports_overall_score_range"),
        CheckConstraint("status IN ('passed', 'needs_review', 'failed')", name="ck_translation_quality_reports_status"),
        CheckConstraint("mode IN ('deterministic', 'full')", name="ck_translation_quality_reports_mode"),
        Index("ix_translation_quality_reports_segment_id", "segment_id"),
        Index("ix_translation_quality_reports_translation_job_id", "translation_job_id"),
        Index("ix_translation_quality_reports_status", "status"),
        Index(
            "uq_translation_quality_reports_job_evaluator",
            "translation_job_id",
            "evaluator_version",
            unique=True,
            postgresql_where=text("translation_job_id IS NOT NULL"),
            sqlite_where=text("translation_job_id IS NOT NULL"),
        ),
        Index(
            "uq_translation_quality_reports_segment_evaluator",
            "segment_id",
            "evaluator_version",
            "source_checksum",
            "translated_checksum",
            unique=True,
            postgresql_where=text("translation_job_id IS NULL"),
            sqlite_where=text("translation_job_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"), nullable=False)
    translation_job_id: Mapped[int | None] = mapped_column(ForeignKey("translation_jobs.id", ondelete="SET NULL"), nullable=True)
    evaluator_version: Mapped[str] = mapped_column(String(20), nullable=False, server_default="1.0.0")
    mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="deterministic")
    deterministic_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evaluator_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="needs_review")
    issues: Mapped[list[dict[str, Any]]] = mapped_column(IssuesJSON, nullable=False, default=list)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    translated_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    @property
    def score(self) -> int:
        return self.overall_score

    @score.setter
    def score(self, value: int) -> None:
        self.overall_score = int(value)

    @property
    def ai_evaluated(self) -> bool:
        return self.ai_score is not None

    @ai_evaluated.setter
    def ai_evaluated(self, value: bool) -> None:
        self.ai_score = self.ai_score if bool(value) else None

    segment: Mapped["Segment"] = relationship(back_populates="quality_reports")
    translation_job: Mapped["TranslationJob | None"] = relationship(back_populates="quality_reports")
