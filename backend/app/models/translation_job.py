from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class TranslationJob(Base):
    __tablename__ = "translation_jobs"
    __table_args__ = (
        Index("ix_translation_jobs_segment_id", "segment_id"),
        Index("ix_translation_jobs_status", "status"),
        Index("ix_translation_jobs_retry_of_id", "retry_of_id"),
        Index("ix_translation_jobs_queue_order", "status", "queued_at"),
        Index(
            "uq_translation_jobs_active_segment",
            "segment_id",
            unique=True,
            postgresql_where=text("status IN ('pending_enqueue', 'queued', 'running')"),
            sqlite_where=text("status IN ('pending_enqueue', 'queued', 'running')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[int] = mapped_column(
        ForeignKey("segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, server_default="openai")
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pending_enqueue")
    attempt: Mapped[int] = mapped_column(nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(nullable=False, server_default="3")
    retry_of_id: Mapped[int | None] = mapped_column(ForeignKey("translation_jobs.id"), nullable=True)
    stream_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    segment: Mapped["Segment"] = relationship(back_populates="translation_jobs")
    retry_of: Mapped["TranslationJob | None"] = relationship(
        "TranslationJob",
        remote_side="TranslationJob.id",
        back_populates="retries",
        foreign_keys=[retry_of_id],
    )
    retries: Mapped[list["TranslationJob"]] = relationship(
        "TranslationJob",
        back_populates="retry_of",
        foreign_keys="TranslationJob.retry_of_id",
    )
    quality_reports: Mapped[list["TranslationQualityReport"]] = relationship(
        "TranslationQualityReport",
        back_populates="translation_job",
        foreign_keys="TranslationQualityReport.translation_job_id",
    )
