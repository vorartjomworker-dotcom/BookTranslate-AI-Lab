"""Deterministic, fully offline translation QA checks."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.quality.config import QualityConfig, QualityWeights, build_quality_config

QualitySeverity = Literal["info", "warning", "error"]
QualityStatus = Literal["passed", "needs_review", "failed"]


class QualityIssue(BaseModel):
    """A single, strictly typed QA finding. This is the only shape persisted in JSONB."""

    model_config = ConfigDict(extra="forbid")

    code: str
    severity: QualitySeverity
    message: str
    field: str | None = None
    expected: str | None = None
    actual: str | None = None
    score_impact: int = Field(default=0, ge=0, le=100)


_NUMBER_RE = re.compile(r"(?<!\w)[+-]?\d[\d,.]*")
_CURLY_PLACEHOLDER_RE = re.compile(r"\{\{[ \t]*[\w.]+[ \t]*\}\}|\{[ \t]*[\w.]+[ \t]*\}")
_PRINTF_PLACEHOLDER_RE = re.compile(r"%(?:\d+\$)?[sdif]")
_DOLLAR_PLACEHOLDER_RE = re.compile(r"\$\{[ \t]*[\w.]+[ \t]*\}")
_URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>()\"']+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


class DeterministicQualityEvaluator:
    """Rule-based, side-effect-free QA evaluator. Fully deterministic for identical input."""

    def __init__(self, config: QualityConfig | None = None) -> None:
        self.config = config or build_quality_config()

    def evaluate(
        self,
        *,
        source_text: str,
        translated_text: str,
        source_language: str | None = None,
        target_language: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> tuple[int, list[QualityIssue]]:
        weights = self.config.weights
        issues: list[QualityIssue] = []

        source_clean = (source_text or "").strip()
        translated_clean = (translated_text or "").strip()

        if not source_clean:
            issues.append(
                QualityIssue(
                    code="missing_source_text",
                    severity="error",
                    message="Source text is empty.",
                    field="source_text",
                    score_impact=weights.missing_source_text,
                )
            )
        if not translated_clean:
            issues.append(
                QualityIssue(
                    code="missing_translation",
                    severity="error",
                    message="Translated text is empty.",
                    field="translated_text",
                    score_impact=weights.missing_translation,
                )
            )
            return self._finalize_score(issues), issues

        normalized_source = self._normalize(source_clean)
        normalized_translation = self._normalize(translated_clean)

        if normalized_source == normalized_translation:
            issues.append(
                QualityIssue(
                    code="untranslated_text",
                    severity="error",
                    message="Translated text matches the source text exactly.",
                    field="translated_text",
                    expected="Translated output should differ from source text.",
                    actual=translated_clean,
                    score_impact=weights.untranslated_text,
                )
            )

        issues.extend(self._check_source_overlap(source_clean, translated_clean, weights))
        issues.extend(self._check_length_ratio(normalized_source, normalized_translation, weights))
        issues.extend(self._check_numbers(source_clean, translated_clean, weights))
        issues.extend(self._check_placeholders(source_clean, translated_clean, weights))
        issues.extend(self._check_urls(source_clean, translated_clean, weights))
        issues.extend(self._check_emails(source_clean, translated_clean, weights))
        issues.extend(self._check_markdown_headings(source_clean, translated_clean, weights))
        issues.extend(self._check_markdown_lists(source_clean, translated_clean, weights))
        issues.extend(self._check_inline_code(source_clean, translated_clean, weights))
        issues.extend(self._check_control_characters(translated_clean, weights))
        issues.extend(self._check_repetition(translated_clean, weights))
        issues.extend(self._check_encoding(translated_clean, weights))

        return self._finalize_score(issues), issues

    @staticmethod
    def _finalize_score(issues: list[QualityIssue]) -> int:
        return max(0, min(100, 100 - sum(issue.score_impact for issue in issues)))

    @staticmethod
    def _normalize(value: str) -> str:
        value = value.strip().lower()
        value = re.sub(r"[^\w\s]", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    @staticmethod
    def _tokenize(value: str) -> list[str]:
        return [token for token in value.split() if token]

    def _check_source_overlap(self, source_text: str, translated_text: str, weights: QualityWeights) -> list[QualityIssue]:
        def _filtered_tokens(value: str) -> set[str]:
            sanitized = re.sub(r"\{\{?\s*[\w.]+\s*\}?\}", " ", value)
            sanitized = re.sub(r"\$\{\s*[\w.]+\s*\}", " ", sanitized)
            sanitized = re.sub(r"%(?:\d+\$)?[sdif]", " ", sanitized)
            return set(self._tokenize(self._normalize(sanitized)))

        normalized_source = self._normalize(source_text)
        normalized_translation = self._normalize(translated_text)
        source_tokens = _filtered_tokens(source_text)
        translation_tokens = _filtered_tokens(translated_text)
        if not source_tokens or not translation_tokens or normalized_source == normalized_translation:
            return []
        overlap = len(source_tokens & translation_tokens) / max(1, len(source_tokens))
        if overlap >= 0.75:
            return [
                QualityIssue(
                    code="source_overlap",
                    severity="warning",
                    message="Translation still contains a high proportion of source tokens.",
                    field="translated_text",
                    expected="Lower overlap between source and translated vocabulary.",
                    actual=f"{overlap:.0%} overlap",
                    score_impact=weights.source_overlap,
                )
            ]
        return []

    def _check_length_ratio(self, normalized_source: str, normalized_translation: str, weights: QualityWeights) -> list[QualityIssue]:
        if not normalized_source or not normalized_translation:
            return []
        issues: list[QualityIssue] = []
        source_length = len(normalized_source)
        translation_length = len(normalized_translation)
        if translation_length < source_length * 0.2:
            issues.append(
                QualityIssue(
                    code="translation_too_short",
                    severity="warning",
                    message="Translated text is significantly shorter than the source.",
                    field="translated_text",
                    expected=f"At least {source_length * 0.2:.0f} normalized characters.",
                    actual=f"{translation_length} normalized characters",
                    score_impact=weights.translation_too_short,
                )
            )
        elif translation_length > source_length * 4.0:
            issues.append(
                QualityIssue(
                    code="translation_too_long",
                    severity="warning",
                    message="Translated text is much longer than the source and may be inflated.",
                    field="translated_text",
                    expected=f"No more than {source_length * 4.0:.0f} normalized characters.",
                    actual=f"{translation_length} normalized characters",
                    score_impact=weights.translation_too_long,
                )
            )
        return issues

    def _check_numbers(self, source: str, translated: str, weights: QualityWeights) -> list[QualityIssue]:
        source_numbers = self._counter(_NUMBER_RE.findall(source))
        translated_numbers = self._counter(_NUMBER_RE.findall(translated))
        issues: list[QualityIssue] = []
        lost = self._missing_items(source_numbers, translated_numbers)
        added = self._missing_items(translated_numbers, source_numbers)
        if lost:
            issues.append(
                QualityIssue(
                    code="lost_numbers",
                    severity="error",
                    message="Numbers present in the source are missing from the translation.",
                    field="translated_text",
                    expected=", ".join(sorted(source_numbers)),
                    actual=", ".join(sorted(lost)),
                    score_impact=weights.lost_numbers,
                )
            )
        if added:
            issues.append(
                QualityIssue(
                    code="added_numbers",
                    severity="warning",
                    message="Translation introduces numbers not present in the source.",
                    field="translated_text",
                    expected=", ".join(sorted(source_numbers)) or "(none)",
                    actual=", ".join(sorted(added)),
                    score_impact=weights.added_numbers,
                )
            )
        return issues

    def _check_placeholders(self, source: str, translated: str, weights: QualityWeights) -> list[QualityIssue]:
        patterns = (_CURLY_PLACEHOLDER_RE, _PRINTF_PLACEHOLDER_RE, _DOLLAR_PLACEHOLDER_RE)
        source_placeholders: set[str] = set()
        translated_placeholders: set[str] = set()
        for pattern in patterns:
            source_placeholders.update(pattern.findall(source))
            translated_placeholders.update(pattern.findall(translated))
        if source_placeholders != translated_placeholders:
            return [
                QualityIssue(
                    code="placeholder_mismatch",
                    severity="error",
                    message="Placeholder tokens differ between source and translation.",
                    field="translated_text",
                    expected=", ".join(sorted(source_placeholders)) or "(none)",
                    actual=", ".join(sorted(translated_placeholders)) or "(none)",
                    score_impact=weights.placeholder_mismatch,
                )
            ]
        return []

    def _check_urls(self, source: str, translated: str, weights: QualityWeights) -> list[QualityIssue]:
        source_urls = set(_URL_RE.findall(source))
        translated_urls = set(_URL_RE.findall(translated))
        if source_urls != translated_urls:
            return [
                QualityIssue(
                    code="url_mismatch",
                    severity="warning",
                    message="URLs differ between source and translation.",
                    field="translated_text",
                    expected=", ".join(sorted(source_urls)) or "(none)",
                    actual=", ".join(sorted(translated_urls)) or "(none)",
                    score_impact=weights.url_mismatch,
                )
            ]
        return []

    def _check_emails(self, source: str, translated: str, weights: QualityWeights) -> list[QualityIssue]:
        source_emails = set(_EMAIL_RE.findall(source))
        translated_emails = set(_EMAIL_RE.findall(translated))
        if source_emails != translated_emails:
            return [
                QualityIssue(
                    code="email_mismatch",
                    severity="warning",
                    message="Email addresses differ between source and translation.",
                    field="translated_text",
                    expected=", ".join(sorted(source_emails)) or "(none)",
                    actual=", ".join(sorted(translated_emails)) or "(none)",
                    score_impact=weights.email_mismatch,
                )
            ]
        return []

    def _check_markdown_headings(self, source: str, translated: str, weights: QualityWeights) -> list[QualityIssue]:
        source_levels = [len(match) for match in _HEADING_RE.findall(source)]
        translated_levels = [len(match) for match in _HEADING_RE.findall(translated)]
        if source_levels != translated_levels:
            return [
                QualityIssue(
                    code="markdown_heading_mismatch",
                    severity="warning",
                    message="Markdown heading structure differs between source and translation.",
                    field="translated_text",
                    expected=str(source_levels),
                    actual=str(translated_levels),
                    score_impact=weights.markdown_heading_mismatch,
                )
            ]
        return []

    def _check_markdown_lists(self, source: str, translated: str, weights: QualityWeights) -> list[QualityIssue]:
        source_count = len(_LIST_ITEM_RE.findall(source))
        translated_count = len(_LIST_ITEM_RE.findall(translated))
        if source_count != translated_count:
            return [
                QualityIssue(
                    code="markdown_list_mismatch",
                    severity="warning",
                    message="Markdown list item count differs between source and translation.",
                    field="translated_text",
                    expected=str(source_count),
                    actual=str(translated_count),
                    score_impact=weights.markdown_list_mismatch,
                )
            ]
        return []

    def _check_inline_code(self, source: str, translated: str, weights: QualityWeights) -> list[QualityIssue]:
        source_code = set(_INLINE_CODE_RE.findall(source))
        translated_code = set(_INLINE_CODE_RE.findall(translated))
        if source_code != translated_code:
            return [
                QualityIssue(
                    code="inline_code_mismatch",
                    severity="warning",
                    message="Inline code spans differ between source and translation.",
                    field="translated_text",
                    expected=", ".join(sorted(source_code)) or "(none)",
                    actual=", ".join(sorted(translated_code)) or "(none)",
                    score_impact=weights.inline_code_mismatch,
                )
            ]
        return []

    def _check_control_characters(self, translated: str, weights: QualityWeights) -> list[QualityIssue]:
        matches = _CONTROL_CHAR_RE.findall(translated)
        if matches:
            return [
                QualityIssue(
                    code="control_characters",
                    severity="error",
                    message="Translated text contains disallowed control characters.",
                    field="translated_text",
                    actual=", ".join(sorted({repr(char) for char in matches})),
                    score_impact=weights.control_characters,
                )
            ]
        return []

    def _check_repetition(self, translated: str, weights: QualityWeights) -> list[QualityIssue]:
        words = _WORD_RE.findall(translated.lower())
        run_length = 1
        max_run = 1
        repeated_word = None
        for previous, current in zip(words, words[1:]):
            if current == previous:
                run_length += 1
                if run_length > max_run:
                    max_run = run_length
                    repeated_word = current
            else:
                run_length = 1
        if max_run >= 5:
            return [
                QualityIssue(
                    code="excessive_repetition",
                    severity="warning",
                    message="Translation contains an excessively repeated word run.",
                    field="translated_text",
                    actual=f"'{repeated_word}' repeated {max_run} times consecutively",
                    score_impact=weights.excessive_repetition,
                )
            ]
        return []

    def _check_encoding(self, translated: str, weights: QualityWeights) -> list[QualityIssue]:
        if "\ufffd" in translated:
            return [
                QualityIssue(
                    code="encoding_issue",
                    severity="error",
                    message="Translation contains the Unicode replacement character, indicating an encoding problem.",
                    field="translated_text",
                    score_impact=weights.encoding_issue,
                )
            ]
        try:
            unicodedata.normalize("NFC", translated)
        except (ValueError, TypeError):
            return [
                QualityIssue(
                    code="encoding_issue",
                    severity="error",
                    message="Translation contains malformed Unicode data.",
                    field="translated_text",
                    score_impact=weights.encoding_issue,
                )
            ]
        return []

    @staticmethod
    def _counter(values: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        return counts

    @staticmethod
    def _missing_items(reference: dict[str, int], other: dict[str, int]) -> list[str]:
        missing: list[str] = []
        for value, count in reference.items():
            if other.get(value, 0) < count:
                missing.append(value)
        return missing
