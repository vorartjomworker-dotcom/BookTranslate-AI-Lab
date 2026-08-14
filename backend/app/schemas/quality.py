from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QualityIssueRead(BaseModel):
    code: str
    severity: str = Field(default="warning")
    message: str
    field: str | None = None
    expected: str | None = None
    actual: str | None = None
    score_impact: int = 0

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class TranslationQualityReportRead(BaseModel):
    id: int
    segment_id: int
    translation_job_id: int | None = None
    evaluator_version: str
    mode: str
    deterministic_score: int = 0
    ai_score: int | None = None
    overall_score: int = 0
    evaluator_error_code: str | None = None
    score: int = 0
    status: str = "needs_review"
    summary: str = ""
    provider: str | None = None
    model: str | None = None
    source_language: str | None = None
    target_language: str | None = None
    ai_evaluated: bool = False
    issues: list[QualityIssueRead] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @property
    def legacy_score(self) -> int:
        return self.overall_score


class QualityCheckRequest(BaseModel):
    mode: Literal["deterministic", "full"] = "deterministic"

    model_config = ConfigDict(extra="forbid")


class BookQualitySummaryRead(BaseModel):
    book_id: int
    total_segments: int
    translated_segments: int
    checked_segments: int
    passed: int
    needs_review: int
    failed: int
    stale_reports: int
    average_score: float | None = None

    model_config = ConfigDict(from_attributes=True)

