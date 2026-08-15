from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SegmentBase(BaseModel):
    segment_number: int = Field(..., ge=1)
    original_text: str = Field(..., min_length=1)
    translated_text: str | None = None
    confidence: float = Field(default=0.0, ge=0.0)
    model_used: str | None = Field(default=None, max_length=100)
    status: str = Field(default="pending", min_length=1, max_length=50)
    qa_score: int = Field(default=0, ge=0)
    qa_status: str | None = Field(default=None, max_length=50)
    qa_comment: str | None = None
    translation_profile: str = Field(default="general", min_length=1, max_length=50)
    tokens_used: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)

    model_config = ConfigDict(from_attributes=True)


class SegmentCreate(SegmentBase):
    pass


class SegmentUpdate(BaseModel):
    segment_number: Optional[int] = Field(default=None, ge=1)
    original_text: Optional[str] = Field(default=None, min_length=1)
    translated_text: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0)
    model_used: Optional[str] = Field(default=None, max_length=100)
    status: Optional[str] = Field(default=None, min_length=1, max_length=50)
    qa_score: Optional[int] = Field(default=None, ge=0)
    qa_status: Optional[str] = Field(default=None, max_length=50)
    qa_comment: Optional[str] = None
    translation_profile: Optional[str] = Field(default=None, min_length=1, max_length=50)
    tokens_used: Optional[int] = Field(default=None, ge=0)
    latency_ms: Optional[int] = Field(default=None, ge=0)

    model_config = ConfigDict(from_attributes=True)


class SegmentTranslationUpdate(BaseModel):
    translated_text: Optional[str] = Field(default=None)

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class SegmentRead(SegmentBase):
    id: int
    chapter_id: int

    model_config = ConfigDict(from_attributes=True)
