"""Create the canonical translation_quality_reports table (JSONB issues)."""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: str | None = "003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "translation_quality_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("translation_job_id", sa.Integer(), nullable=True),
        sa.Column("evaluator_version", sa.String(length=20), nullable=False, server_default="1.0.0"),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="deterministic"),
        sa.Column("deterministic_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_score", sa.Integer(), nullable=True),
        sa.Column("overall_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evaluator_error_code", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="needs_review"),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("source_language", sa.String(length=20), nullable=True),
        sa.Column("target_language", sa.String(length=20), nullable=True),
        sa.Column("source_checksum", sa.String(length=64), nullable=False),
        sa.Column("translated_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["translation_job_id"], ["translation_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "deterministic_score >= 0 AND deterministic_score <= 100",
            name="ck_translation_quality_reports_deterministic_score_range",
        ),
        sa.CheckConstraint(
            "(ai_score IS NULL) OR (ai_score >= 0 AND ai_score <= 100)",
            name="ck_translation_quality_reports_ai_score_range",
        ),
        sa.CheckConstraint("overall_score >= 0 AND overall_score <= 100", name="ck_translation_quality_reports_overall_score_range"),
        sa.CheckConstraint("status IN ('passed', 'needs_review', 'failed')", name="ck_translation_quality_reports_status"),
        sa.CheckConstraint("mode IN ('deterministic', 'full')", name="ck_translation_quality_reports_mode"),
    )

    op.create_index(op.f("ix_translation_quality_reports_segment_id"), "translation_quality_reports", ["segment_id"], unique=False)
    op.create_index(op.f("ix_translation_quality_reports_translation_job_id"), "translation_quality_reports", ["translation_job_id"], unique=False)
    op.create_index(op.f("ix_translation_quality_reports_status"), "translation_quality_reports", ["status"], unique=False)
    op.create_index(
        "uq_translation_quality_reports_job_evaluator",
        "translation_quality_reports",
        ["translation_job_id", "evaluator_version"],
        unique=True,
        postgresql_where=sa.text("translation_job_id IS NOT NULL"),
        sqlite_where=sa.text("translation_job_id IS NOT NULL"),
    )
    op.create_index(
        "uq_translation_quality_reports_segment_evaluator",
        "translation_quality_reports",
        ["segment_id", "evaluator_version", "source_checksum", "translated_checksum"],
        unique=True,
        postgresql_where=sa.text("translation_job_id IS NULL"),
        sqlite_where=sa.text("translation_job_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_translation_quality_reports_segment_evaluator", table_name="translation_quality_reports")
    op.drop_index("uq_translation_quality_reports_job_evaluator", table_name="translation_quality_reports")
    op.drop_index(op.f("ix_translation_quality_reports_status"), table_name="translation_quality_reports")
    op.drop_index(op.f("ix_translation_quality_reports_translation_job_id"), table_name="translation_quality_reports")
    op.drop_index(op.f("ix_translation_quality_reports_segment_id"), table_name="translation_quality_reports")
    op.drop_table("translation_quality_reports")
