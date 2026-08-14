from datetime import datetime

from sqlalchemy import String, Text, ForeignKey, DateTime, Float, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("chapter_id", "segment_number", name="uq_segments_chapter_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    segment_number: Mapped[int] = mapped_column(nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.0")
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True, server_default="pending")
    qa_score: Mapped[int] = mapped_column(nullable=False, server_default="0")
    qa_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    qa_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    translation_profile: Mapped[str] = mapped_column(String(50), nullable=False, server_default="general")
    tokens_used: Mapped[int] = mapped_column(nullable=False, server_default="0")
    latency_ms: Mapped[int] = mapped_column(nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    chapter: Mapped["Chapter"] = relationship(back_populates="segments")
    translation_jobs: Mapped[list["TranslationJob"]] = relationship(
        back_populates="segment",
        cascade="all, delete-orphan",
    )
