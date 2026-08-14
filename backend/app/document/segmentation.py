from __future__ import annotations

import re
from typing import Iterable

from app.core.config import settings


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"\s+")


class TextSegmenter:
    def __init__(
        self,
        target_chars: int | None = None,
        hard_limit: int | None = None,
        *,
        hard_limit_chars: int | None = None,
    ) -> None:
        self.target_chars = target_chars if target_chars is not None else settings.segment_target_chars
        self.hard_limit = hard_limit if hard_limit is not None else (hard_limit_chars if hard_limit_chars is not None else settings.segment_hard_limit_chars)

    def segment(self, text: str) -> list[str]:
        normalized = self._normalize(text)
        if not normalized:
            return []

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", normalized) if p.strip()]
        segments: list[str] = []
        for paragraph in paragraphs:
            segments.extend(self._segment_paragraph(paragraph))
        return [s for s in segments if s.strip()]

    def _normalize(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return "\n\n".join(part.strip() for part in text.split("\n") if part.strip())

    def _segment_paragraph(self, paragraph: str) -> list[str]:
        if len(paragraph) <= self.target_chars:
            return self._split_long_sentence(paragraph)

        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(paragraph) if s.strip()]
        current = ""
        chunks: list[str] = []
        for sentence in sentences:
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= self.target_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(sentence) <= self.hard_limit:
                current = sentence
            else:
                chunks.extend(self._split_word_run(sentence))
                current = ""
        if current:
            chunks.append(current)
        condensed: list[str] = []
        for chunk in chunks:
            condensed.extend(self._split_word_run(chunk))
        return condensed

    def _split_long_sentence(self, text: str) -> list[str]:
        if len(text) <= self.hard_limit:
            return [text]
        words = [word for word in _WORD_SPLIT.split(text) if word]
        chunks: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip() if current else word
            if len(candidate) <= self.hard_limit:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = word
        if current:
            chunks.append(current)
        return chunks

    def _split_word_run(self, text: str) -> list[str]:
        if len(text) <= self.hard_limit:
            return [text]
        words = [word for word in _WORD_SPLIT.split(text) if word]
        chunks: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip() if current else word
            if len(candidate) <= self.hard_limit:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = word
        if current:
            chunks.append(current)
        return [chunk for chunk in chunks if chunk.strip()]
