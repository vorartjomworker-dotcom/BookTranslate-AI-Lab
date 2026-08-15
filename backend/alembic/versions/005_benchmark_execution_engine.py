"""Create benchmark execution engine tables and indexes."""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: str | None = "004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmark_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("dataset_name", sa.String(length=120), nullable=False),
        sa.Column("dataset_version", sa.String(length=50), nullable=False),
        sa.Column("dataset_checksum", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("evaluator_version", sa.String(length=50), nullable=False, server_default="1.0.0"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("seed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("concurrency", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_cases", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("max_budget_usd", sa.Float(), nullable=False, server_default="5.0"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("confirm_live_provider", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("execution_contract", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("pricing_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("category_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'partially_failed', 'failed', 'cancelled')", name="ck_benchmark_runs_status"),
        sa.CheckConstraint("max_cases > 0", name="ck_benchmark_runs_max_cases_positive"),
        sa.CheckConstraint("concurrency > 0", name="ck_benchmark_runs_concurrency_positive"),
        sa.CheckConstraint("timeout_seconds > 0", name="ck_benchmark_runs_timeout_positive"),
        sa.CheckConstraint("max_budget_usd >= 0", name="ck_benchmark_runs_budget_non_negative"),
        sa.CheckConstraint("seed >= 0", name="ck_benchmark_runs_seed_non_negative"),
    )

    op.create_table(
        "benchmark_case_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("qa_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("qa_passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["benchmark_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "case_id", name="uq_benchmark_case_results_run_case"),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'cancelled')", name="ck_benchmark_case_results_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_benchmark_case_results_attempt_count"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_benchmark_case_results_latency"),
        sa.CheckConstraint("input_tokens >= 0", name="ck_benchmark_case_results_input_tokens"),
        sa.CheckConstraint("output_tokens >= 0", name="ck_benchmark_case_results_output_tokens"),
        sa.CheckConstraint("total_tokens >= 0", name="ck_benchmark_case_results_total_tokens"),
        sa.CheckConstraint("estimated_cost_usd >= 0", name="ck_benchmark_case_results_estimated_cost"),
        sa.CheckConstraint("qa_score >= 0 AND qa_score <= 100", name="ck_benchmark_case_results_qa_score"),
    )

    op.create_index(op.f("ix_benchmark_runs_run_id"), "benchmark_runs", ["run_id"], unique=True)
    op.create_index(op.f("ix_benchmark_runs_status"), "benchmark_runs", ["status"], unique=False)
    op.create_index(op.f("ix_benchmark_runs_provider_model"), "benchmark_runs", ["provider", "model"], unique=False)
    op.create_index(op.f("ix_benchmark_runs_created_at"), "benchmark_runs", ["created_at"], unique=False)
    op.create_index(op.f("ix_benchmark_case_results_run_id"), "benchmark_case_results", ["run_id"], unique=False)
    op.create_index(op.f("ix_benchmark_case_results_case_id"), "benchmark_case_results", ["case_id"], unique=False)
    op.create_index(op.f("ix_benchmark_case_results_status"), "benchmark_case_results", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_benchmark_case_results_status"), table_name="benchmark_case_results")
    op.drop_index(op.f("ix_benchmark_case_results_case_id"), table_name="benchmark_case_results")
    op.drop_index(op.f("ix_benchmark_case_results_run_id"), table_name="benchmark_case_results")
    op.drop_index(op.f("ix_benchmark_runs_created_at"), table_name="benchmark_runs")
    op.drop_index(op.f("ix_benchmark_runs_provider_model"), table_name="benchmark_runs")
    op.drop_index(op.f("ix_benchmark_runs_status"), table_name="benchmark_runs")
    op.drop_index(op.f("ix_benchmark_runs_run_id"), table_name="benchmark_runs")
    op.drop_table("benchmark_case_results")
    op.drop_table("benchmark_runs")
