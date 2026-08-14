from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ParsedChapter:
    title: str
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedDocument:
    title: str
    author: str | None = None
    language: str | None = None
    description: str | None = None
    chapters: list[ParsedChapter] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_text(self) -> str:
        return "\n\n".join(chapter.content for chapter in self.chapters if chapter.content.strip())
