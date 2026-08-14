from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

VALID_STATUS_VALUES = {"pending_enqueue", "queued", "running", "completed", "failed"}


class TranslationJobBase(BaseModel):
    segment_id: int = Field(..., gt=0)
    provider: str = Field(default="openai", min_length=1, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    status: str = Field(default="pending_enqueue", min_length=1, max_length=50)
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    retry_of_id: int | None = None
    stream_message_id: str | None = None
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in VALID_STATUS_VALUES:
            raise ValueError("status must be one of pending_enqueue, queued, running, completed, failed")
        return normalized


class TranslationJobCreate(BaseModel):
    provider: str | None = Field(default=None, min_length=1, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    max_attempts: int | None = Field(default=None, ge=1)


class TranslationJobRead(TranslationJobBase):
    id: int
    created_at: datetime | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    request_id: str | None = None

    model_config = ConfigDict(from_attributes=True)
