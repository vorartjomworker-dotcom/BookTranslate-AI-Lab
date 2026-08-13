from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BookBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    author: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None)
    file_path: str = Field(..., min_length=1, max_length=512)
    file_type: str = Field(..., min_length=1, max_length=10)
    language: str = Field(default="unknown", min_length=1, max_length=20)
    status: str = Field(default="uploaded", min_length=1, max_length=50)

    model_config = ConfigDict(from_attributes=True)


class BookCreate(BookBase):
    pass


class BookUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    author: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    file_path: Optional[str] = Field(default=None, min_length=1, max_length=512)
    file_type: Optional[str] = Field(default=None, min_length=1, max_length=10)
    language: Optional[str] = Field(default=None, min_length=1, max_length=20)
    status: Optional[str] = Field(default=None, min_length=1, max_length=50)

    model_config = ConfigDict(from_attributes=True)


class BookRead(BookBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
