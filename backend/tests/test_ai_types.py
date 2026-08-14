import pytest

from app.ai.types import TranslationRequest


def test_translation_request_validates_required_fields():
    request = TranslationRequest(text="Hello world", source_language="en", target_language="ru")
    assert request.text == "Hello world"
    assert request.profile == "general"


def test_translation_request_rejects_empty_text():
    with pytest.raises(ValueError):
        TranslationRequest(text="   ", source_language="en", target_language="ru")


def test_translation_request_rejects_same_language_after_normalization():
    with pytest.raises(ValueError):
        TranslationRequest(text="Hello", source_language="EN", target_language="en")


def test_translation_request_rejects_invalid_profile():
    with pytest.raises(ValueError):
        TranslationRequest(text="Hello", source_language="en", target_language="ru", profile="invalid")


def test_translation_request_validates_glossary_and_context():
    request = TranslationRequest(
        text="Hello",
        source_language="en",
        target_language="ru",
        glossary={"hello": "привет"},
        context="This is a technical report.",
    )
    assert request.glossary == {"hello": "привет"}
    assert request.context == "This is a technical report."


def test_translation_request_rejects_large_context():
    with pytest.raises(ValueError):
        TranslationRequest(
            text="Hello",
            source_language="en",
            target_language="ru",
            context="x" * 50000,
        )
