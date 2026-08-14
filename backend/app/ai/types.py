from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VALID_PROFILES = ("general", "technical", "literary", "academic")
PROFILE_LITERAL = Literal["general", "technical", "literary", "academic"]


class TranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    source_language: str
    target_language: str
    provider: str | None = None
    model: str | None = None
    profile: PROFILE_LITERAL = "general"
    glossary: dict[str, str] = Field(default_factory=dict)
    context: str | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if value is None or not value.strip():
            raise ValueError("text must be a non-empty string")
        return value.strip()

    @field_validator("source_language", "target_language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        if value is None or not str(value).strip():
            raise ValueError("language names must be non-empty")
        return str(value).strip().lower()

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str) -> str:
        if value not in VALID_PROFILES:
            raise ValueError(f"profile must be one of {VALID_PROFILES}")
        return value

    @field_validator("glossary")
    @classmethod
    def validate_glossary(cls, value: dict[str, str] | None) -> dict[str, str]:
        if value is None:
            return {}
        result: dict[str, str] = {}
        for key, val in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("glossary keys must be non-empty strings")
            if not isinstance(val, str):
                raise ValueError("glossary values must be strings")
            result[key.strip()] = val.strip()
        return result

    @field_validator("context")
    @classmethod
    def validate_context(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > 12000:
            raise ValueError("context exceeds supported maximum length")
        return value or None

    @model_validator(mode="after")
    def validate_languages_and_pairing(self) -> "TranslationRequest":
        src = self.source_language.lower()
        dst = self.target_language.lower()
        if src == dst:
            raise ValueError("source_language and target_language must differ")
        return self


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class TranslationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translated_text: str
    provider: str
    model: str | None = None
    source_language: str
    target_language: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    confidence: float | None = None
    finish_reason: str | None = None

    @field_validator("translated_text")
    @classmethod
    def validate_translated_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("translated_text must not be empty")
        return value

    @property
    def token_usage(self) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.total_tokens,
        )
