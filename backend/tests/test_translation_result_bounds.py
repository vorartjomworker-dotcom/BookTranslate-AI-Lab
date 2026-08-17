from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.types import MAX_TRANSLATED_TEXT_CHARS, TranslationResult


def _result(text: str) -> TranslationResult:
    return TranslationResult(
        translated_text=text,
        provider="openai",
        model="gpt-test",
        source_language="en",
        target_language="ru",
    )


def test_translation_result_accepts_text_at_provider_output_bound() -> None:
    text = "x" * MAX_TRANSLATED_TEXT_CHARS

    result = _result(text)

    assert result.translated_text == text


def test_translation_result_rejects_oversized_provider_output() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _result("x" * (MAX_TRANSLATED_TEXT_CHARS + 1))

    assert "translated_text exceeds supported maximum length" in str(excinfo.value)


def test_translation_result_still_rejects_blank_output() -> None:
    with pytest.raises(ValidationError):
        _result("   ")
