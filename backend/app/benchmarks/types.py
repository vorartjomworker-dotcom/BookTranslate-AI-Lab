from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BenchmarkStatus = Literal["pending", "running", "completed", "partially_failed", "failed", "cancelled"]
BenchmarkCaseStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    source_language: str = Field(..., min_length=2, max_length=20)
    target_language: str = Field(..., min_length=2, max_length=20)
    source_text: str = Field(..., min_length=1)
    reference_translation: str | None = None
    protected_tokens: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_language", "target_language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("protected_tokens")
    @classmethod
    def normalize_tokens(cls, value: list[str]) -> list[str]:
        return sorted({token.strip() for token in value if isinstance(token, str) and token.strip()})


class BenchmarkDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    checksum: str
    description: str
    source: str
    cases: list[BenchmarkCase] = Field(default_factory=list)


class BenchmarkExecutionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    dataset_name: str
    dataset_version: str
    dataset_checksum: str
    seed: int = 0
    max_cases: int = 10
    concurrency: int = 1
    timeout_seconds: int = 30
    max_retries: int = 2
    max_budget_usd: float = 5.0
    dry_run: bool = True
    confirm_live_provider: bool = False
    executor_version: str = "1.0.0"


class BenchmarkCaseResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    status: BenchmarkCaseStatus
    attempt_count: int = 0
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    qa_score: float = 0.0
    qa_passed: bool = False
    error_code: str | None = None
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class PricingSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    currency: str = "USD"
    input_cost_per_1k_tokens: float = 0.0
    output_cost_per_1k_tokens: float = 0.0
    effective_date: str
    version: str
    source: str
