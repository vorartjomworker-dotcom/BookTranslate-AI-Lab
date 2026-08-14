"""Create TranslationJob table and active job uniqueness guard."""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "translation_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="openai"),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending_enqueue"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("retry_of_id", sa.Integer(), nullable=True),
        sa.Column("stream_message_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("queued_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["retry_of_id"], ["translation_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_translation_jobs_segment_id"), "translation_jobs", ["segment_id"], unique=False)
    op.create_index(op.f("ix_translation_jobs_status"), "translation_jobs", ["status"], unique=False)
    op.create_index(op.f("ix_translation_jobs_retry_of_id"), "translation_jobs", ["retry_of_id"], unique=False)
    op.create_index(op.f("ix_translation_jobs_queue_order"), "translation_jobs", ["status", "queued_at"], unique=False)
    op.create_index(
        "uq_translation_jobs_active_segment",
        "translation_jobs",
        ["segment_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending_enqueue', 'queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_translation_jobs_active_segment", table_name="translation_jobs")
    op.drop_index(op.f("ix_translation_jobs_queue_order"), table_name="translation_jobs")
    op.drop_index(op.f("ix_translation_jobs_retry_of_id"), table_name="translation_jobs")
    op.drop_index(op.f("ix_translation_jobs_status"), table_name="translation_jobs")
    op.drop_index(op.f("ix_translation_jobs_segment_id"), table_name="translation_jobs")
    op.drop_table("translation_jobs")
