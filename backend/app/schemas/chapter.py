from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ChapterBase(BaseModel):
    chapter_number: int = Field(..., ge=1)
    title: str = Field(..., min_length=1, max_length=255)
    content: str | None = None
    status: str = Field(default="pending", min_length=1, max_length=50)

    model_config = ConfigDict(from_attributes=True)


class ChapterCreate(ChapterBase):
    pass


class ChapterUpdate(BaseModel):
    chapter_number: Optional[int] = Field(default=None, ge=1)
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    content: Optional[str] = None
    status: Optional[str] = Field(default=None, min_length=1, max_length=50)

    model_config = ConfigDict(from_attributes=True)


class ChapterRead(ChapterBase):
    id: int
    book_id: int

    model_config = ConfigDict(from_attributes=True)
