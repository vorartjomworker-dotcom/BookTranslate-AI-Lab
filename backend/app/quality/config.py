"""Validated configuration for deterministic QA thresholds and issue weights."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings


class QualityThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    pass_threshold: int = Field(default=85, ge=0, le=100)
    review_threshold: int = Field(default=60, ge=0, le=100)
    auto_approve_score: int | None = Field(default=None, exclude=True)
    needs_review_floor: int | None = Field(default=None, exclude=True)
    failed_floor: int | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def validate_order(self) -> "QualityThresholds":
        if self.auto_approve_score is not None and self.auto_approve_score != self.pass_threshold:
            raise ValueError("auto_approve_score must match pass_threshold when provided")
        if self.needs_review_floor is not None and self.needs_review_floor != self.review_threshold:
            raise ValueError("needs_review_floor must match review_threshold when provided")
        if not (0 <= self.review_threshold < self.pass_threshold <= 100):
            raise ValueError("quality thresholds must satisfy 0 <= review_threshold < pass_threshold <= 100")
        self.auto_approve_score = self.pass_threshold
        self.needs_review_floor = self.review_threshold
        self.failed_floor = max(0, self.review_threshold - 1)
        return self


class QualityWeights(BaseModel):
    """Score-impact weights applied per deterministic issue code."""

    model_config = ConfigDict(extra="forbid")

    missing_source_text: int = 30
    missing_translation: int = 60
    untranslated_text: int = 75
    source_overlap: int = 20
    translation_too_short: int = 25
    translation_too_long: int = 15
    lost_numbers: int = 20
    added_numbers: int = 10
    placeholder_mismatch: int = 25
    url_mismatch: int = 15
    email_mismatch: int = 15
    markdown_heading_mismatch: int = 10
    markdown_list_mismatch: int = 10
    inline_code_mismatch: int = 15
    control_characters: int = 10
    excessive_repetition: int = 10
    encoding_issue: int = 10

    @field_validator("*")
    @classmethod
    def validate_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("quality weights must be >= 0")
        return value


class QualityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluator_version: str
    thresholds: QualityThresholds
    weights: QualityWeights = Field(default_factory=QualityWeights)
    deterministic_weight: float = Field(default=0.8, ge=0.0, le=1.0)
    ai_weight: float = Field(default=0.2, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_score_weights(self) -> "QualityConfig":
        if abs(self.deterministic_weight + self.ai_weight - 1.0) > 1e-9:
            raise ValueError("deterministic_weight and ai_weight must sum to 1")
        return self


def build_quality_config() -> QualityConfig:
    """Build a validated QA config snapshot from application settings."""
    return QualityConfig(
        evaluator_version=settings.quality_evaluator_version,
        thresholds=QualityThresholds(
            pass_threshold=settings.quality_pass_threshold,
            review_threshold=settings.quality_review_threshold,
        ),
        weights=QualityWeights(),
        deterministic_weight=settings.quality_deterministic_weight,
        ai_weight=settings.quality_ai_weight,
    )
