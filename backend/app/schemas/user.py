from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic_core import PydanticCustomError

from app.core.security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH


class UserRead(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=PASSWORD_MAX_LENGTH)

    model_config = ConfigDict(extra="forbid")


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    role: str = Field(default="viewer", pattern="^(admin|editor|viewer)$")

    model_config = ConfigDict(extra="forbid")


class UserUpdate(BaseModel):
    # PATCH semantics: fields may be omitted, but explicit JSON null is forbidden
    # because both database columns are NOT NULL.
    role: str | None = Field(default=None, pattern="^(admin|editor|viewer)$")
    is_active: bool | None = None

    @field_validator("role", "is_active", mode="before")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise PydanticCustomError(
                "null_not_allowed",
                "Field may be omitted but must not be null when provided.",
            )
        return value

    model_config = ConfigDict(extra="forbid")
