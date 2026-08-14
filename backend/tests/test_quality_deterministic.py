from __future__ import annotations

import json

import pytest

from app.quality.config import QualityConfig, QualityThresholds, QualityWeights
from app.quality.deterministic import DeterministicQualityEvaluator, QualityIssue
from app.quality.service import QualityAssuranceService


def _assert_issue_safety(issues: list[QualityIssue], source_text: str, translated_text: str) -> None:
    payload = json.dumps([issue.model_dump(mode="json") for issue in issues], ensure_ascii=False)
    if source_text:
        assert source_text not in payload
    if translated_text:
        assert translated_text not in payload


def test_deterministic_quality_detects_valid_translation_without_issues() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(
        source_text="The quick brown fox jumps over the lazy dog.",
        translated_text="Le renard brun et rapide saute par-dessus le chien paresseux.",
    )
    assert score == 100
    assert issues == []


def test_deterministic_quality_detects_empty_translation() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="hello world", translated_text="")
    assert score == 40
    assert any(issue.code == "missing_translation" for issue in issues)
    assert issues[0].severity == "error"


def test_deterministic_quality_detects_source_same_as_translation() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="hello world", translated_text="hello world")
    assert score == 25
    assert any(issue.code == "untranslated_text" for issue in issues)
    assert issues[0].severity == "error"


def test_deterministic_quality_detects_too_short_length_ratio() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(
        source_text="This is a very long source sentence with many words.",
        translated_text="short",
    )
    assert score < 100
    assert any(issue.code == "translation_too_short" for issue in issues)


def test_deterministic_quality_detects_too_large_length_ratio() -> None:
    evaluator = DeterministicQualityEvaluator()
    source_text = "Short."
    translated_text = "This translation is intentionally much longer than the source sentence and should trigger the length warning."
    score, issues = evaluator.evaluate(source_text=source_text, translated_text=translated_text)
    assert score < 100
    assert any(issue.code == "translation_too_long" for issue in issues)


def test_deterministic_quality_detects_lost_number() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(
        source_text="The order includes 3 apples and 5 oranges.",
        translated_text="The order includes apples and oranges.",
    )
    assert score < 100
    assert any(issue.code == "lost_numbers" for issue in issues)
    _assert_issue_safety(issues, "The order includes 3 apples and 5 oranges.", "The order includes apples and oranges.")


def test_deterministic_quality_detects_added_number() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(
        source_text="The order includes apples and oranges.",
        translated_text="The order includes 3 apples and oranges.",
    )
    assert score < 100
    assert any(issue.code == "added_numbers" for issue in issues)


def test_deterministic_quality_keeps_valid_numbers() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(
        source_text="The order includes 3 apples and 5 oranges.",
        translated_text="The order includes 3 apples and 5 oranges.",
    )
    assert score == 25
    assert not any(issue.code == "lost_numbers" for issue in issues)
    assert not any(issue.code == "added_numbers" for issue in issues)


def test_deterministic_quality_detects_lost_single_curly_placeholder() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="Hello {name}", translated_text="Hello")
    assert score < 100
    assert any(issue.code == "placeholder_mismatch" for issue in issues)


def test_deterministic_quality_detects_lost_double_curly_placeholder() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="Hello {{name}}", translated_text="Hello")
    assert score < 100
    assert any(issue.code == "placeholder_mismatch" for issue in issues)


def test_deterministic_quality_detects_lost_printf_placeholder() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="Hello %s", translated_text="Hello")
    assert score < 100
    assert any(issue.code == "placeholder_mismatch" for issue in issues)


def test_deterministic_quality_detects_lost_decimal_printf_placeholder() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="Value %d", translated_text="Value")
    assert score < 100
    assert any(issue.code == "placeholder_mismatch" for issue in issues)


def test_deterministic_quality_detects_lost_dollar_placeholder() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="Price is ${name}", translated_text="Price is")
    assert score < 100
    assert any(issue.code == "placeholder_mismatch" for issue in issues)


def test_deterministic_quality_keeps_all_placeholders() -> None:
    evaluator = DeterministicQualityEvaluator()
    source_text = "Hello {name} {{name}} %s %d ${name}"
    translated_text = "Bonjour {name} {{name}} %s %d ${name}"
    score, issues = evaluator.evaluate(source_text=source_text, translated_text=translated_text)
    assert score == 100
    assert not any(issue.code == "placeholder_mismatch" for issue in issues)


def test_deterministic_quality_detects_lost_url() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="Visit https://example.com", translated_text="Visit")
    assert score < 100
    assert any(issue.code == "url_mismatch" for issue in issues)


def test_deterministic_quality_detects_lost_email() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="Contact foo@example.com", translated_text="Contact")
    assert score < 100
    assert any(issue.code == "email_mismatch" for issue in issues)


def test_deterministic_quality_detects_markdown_heading_mismatch() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="# Title\n## Subtitle", translated_text="## Title\n## Subtitle")
    assert score < 100
    assert any(issue.code == "markdown_heading_mismatch" for issue in issues)


def test_deterministic_quality_detects_markdown_list_mismatch() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="- one\n- two", translated_text="- one")
    assert score < 100
    assert any(issue.code == "markdown_list_mismatch" for issue in issues)


def test_deterministic_quality_detects_inline_code_mismatch() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="Run `pytest -q`", translated_text="Run pytest -q")
    assert score < 100
    assert any(issue.code == "inline_code_mismatch" for issue in issues)


def test_deterministic_quality_detects_control_characters() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="clean text", translated_text="bad\x00text")
    assert score < 100
    assert any(issue.code == "control_characters" for issue in issues)


def test_deterministic_quality_detects_excessive_repetition() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="Some text", translated_text="the the the the the")
    assert score < 100
    assert any(issue.code == "excessive_repetition" for issue in issues)


def test_deterministic_quality_accepts_cyrillic_translation() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="Привет, мир!", translated_text="Здравствуйте, мир!")
    assert score == 100
    assert issues == []


def test_deterministic_quality_accepts_unicode_translation() -> None:
    evaluator = DeterministicQualityEvaluator()
    score, issues = evaluator.evaluate(source_text="Café résumé — 東京", translated_text="Кафе резюме — 東京")
    assert score == 100
    assert issues == []


def test_deterministic_quality_is_deterministic_for_identical_input() -> None:
    evaluator = DeterministicQualityEvaluator()
    first_score, first_issues = evaluator.evaluate(source_text="hello world", translated_text="hola mundo")
    second_score, second_issues = evaluator.evaluate(source_text="hello world", translated_text="hola mundo")
    assert first_score == second_score
    assert [issue.code for issue in first_issues] == [issue.code for issue in second_issues]


def test_deterministic_quality_clamps_score_at_zero() -> None:
    evaluator = DeterministicQualityEvaluator()
    score = evaluator._finalize_score([
        QualityIssue(code="issue_a", severity="error", message="A", score_impact=60),
        QualityIssue(code="issue_b", severity="error", message="B", score_impact=60),
        QualityIssue(code="issue_c", severity="error", message="C", score_impact=60),
    ])
    assert score == 0


def test_deterministic_quality_clamps_score_at_hundred() -> None:
    evaluator = DeterministicQualityEvaluator()
    score = evaluator._finalize_score([])
    assert score == 100


def test_quality_status_thresholds_use_pass_threshold_85_and_review_threshold_60() -> None:
    service = QualityAssuranceService.__new__(QualityAssuranceService)
    service.config = QualityConfig(
        evaluator_version="1.0.0",
        thresholds=QualityThresholds(pass_threshold=85, review_threshold=60),
        weights=QualityWeights(),
        deterministic_weight=0.8,
        ai_weight=0.2,
    )
    assert service._score_to_status(85) == "passed"
    assert service._score_to_status(84) == "needs_review"
    assert service._score_to_status(60) == "needs_review"
    assert service._score_to_status(59) == "failed"


def test_quality_config_rejects_invalid_pass_threshold() -> None:
    with pytest.raises(ValueError):
        QualityThresholds(pass_threshold=0, review_threshold=60)


def test_quality_config_rejects_invalid_review_threshold() -> None:
    with pytest.raises(ValueError):
        QualityThresholds(pass_threshold=85, review_threshold=-1)


def test_quality_config_rejects_review_threshold_not_lower_than_pass_threshold() -> None:
    with pytest.raises(ValueError):
        QualityThresholds(pass_threshold=85, review_threshold=85)


def test_quality_config_rejects_negative_weight() -> None:
    with pytest.raises(ValueError):
        QualityConfig(
            evaluator_version="1.0.0",
            thresholds=QualityThresholds(pass_threshold=85, review_threshold=60),
            weights=QualityWeights(),
            deterministic_weight=-0.1,
            ai_weight=1.1,
        )


def test_quality_config_rejects_weight_above_one() -> None:
    with pytest.raises(ValueError):
        QualityConfig(
            evaluator_version="1.0.0",
            thresholds=QualityThresholds(pass_threshold=85, review_threshold=60),
            weights=QualityWeights(),
            deterministic_weight=1.2,
            ai_weight=-0.2,
        )


def test_quality_config_rejects_non_unit_total_weight() -> None:
    with pytest.raises(ValueError):
        QualityConfig(
            evaluator_version="1.0.0",
            thresholds=QualityThresholds(pass_threshold=85, review_threshold=60),
            weights=QualityWeights(),
            deterministic_weight=0.8,
            ai_weight=0.7,
        )
