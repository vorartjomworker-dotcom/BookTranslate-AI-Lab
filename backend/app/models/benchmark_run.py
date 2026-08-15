from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.base import Base

JSONVariant = JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'running', 'completed', 'partially_failed', 'failed', 'cancelled')", name="ck_benchmark_runs_status"),
        CheckConstraint("max_cases > 0", name="ck_benchmark_runs_max_cases_positive"),
        CheckConstraint("concurrency > 0", name="ck_benchmark_runs_concurrency_positive"),
        CheckConstraint("timeout_seconds > 0", name="ck_benchmark_runs_timeout_positive"),
        CheckConstraint("max_budget_usd >= 0", name="ck_benchmark_runs_budget_non_negative"),
        CheckConstraint("seed >= 0", name="ck_benchmark_runs_seed_non_negative"),
        Index("ix_benchmark_runs_status", "status"),
        Index("ix_benchmark_runs_provider_model", "provider", "model"),
        Index("ix_benchmark_runs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    dataset_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(50), nullable=False)
    dataset_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0.0")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    seed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    max_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    max_budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confirm_live_provider: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    execution_contract: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    pricing_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    category_metrics: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    cases: Mapped[list["BenchmarkCaseResult"]] = relationship(back_populates="benchmark_run", cascade="all, delete-orphan")


class BenchmarkCaseResult(Base):
    __tablename__ = "benchmark_case_results"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", name="uq_benchmark_case_results_run_case"),
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'cancelled')", name="ck_benchmark_case_results_status"),
        CheckConstraint("attempt_count >= 0", name="ck_benchmark_case_results_attempt_count"),
        CheckConstraint("latency_ms >= 0", name="ck_benchmark_case_results_latency"),
        CheckConstraint("input_tokens >= 0", name="ck_benchmark_case_results_input_tokens"),
        CheckConstraint("output_tokens >= 0", name="ck_benchmark_case_results_output_tokens"),
        CheckConstraint("total_tokens >= 0", name="ck_benchmark_case_results_total_tokens"),
        CheckConstraint("estimated_cost_usd >= 0", name="ck_benchmark_case_results_estimated_cost"),
        CheckConstraint("qa_score >= 0 AND qa_score <= 100", name="ck_benchmark_case_results_qa_score"),
        Index("ix_benchmark_case_results_run_id", "run_id"),
        Index("ix_benchmark_case_results_case_id", "case_id"),
        Index("ix_benchmark_case_results_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    qa_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    qa_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    benchmark_run: Mapped[BenchmarkRun] = relationship(back_populates="cases")
