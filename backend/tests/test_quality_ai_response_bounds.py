from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.quality.ai_evaluator import AIQualityEvaluator, QualityEvaluationError


class _AsyncResult:
    def __init__(self, value: object) -> None:
        self.value = value

    async def __call__(self, **_kwargs):
        return self.value


def _response(payload: object) -> object:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _evaluator(payload: object) -> AIQualityEvaluator:
    provider = SimpleNamespace(
        validate_configuration=lambda: None,
        client=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=_AsyncResult(_response(payload)))
            )
        ),
    )
    return AIQualityEvaluator(
        registry=SimpleNamespace(get_provider=lambda _name: provider),
        provider_name="openai",
    )


@pytest.mark.asyncio
async def test_ai_quality_evaluator_rejects_too_many_issues() -> None:
    issue = {
        "code": "ai_issue",
        "severity": "warning",
        "message": "bounded issue",
        "score_impact": 1,
    }
    evaluator = _evaluator({"issues": [issue for _ in range(51)]})

    with pytest.raises(QualityEvaluationError) as excinfo:
        await evaluator.evaluate(source_text="hello", translated_text="hola")

    assert excinfo.value.code == "quality_ai_malformed_response"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "oversized_value"),
    [
        ("code", "quality_" + "x" * 100),
        ("message", "m" * 1001),
        ("field", "f" * 101),
        ("expected", "e" * 2001),
        ("actual", "a" * 2001),
    ],
)
async def test_ai_quality_evaluator_rejects_oversized_issue_fields(
    field_name: str,
    oversized_value: str,
) -> None:
    issue = {
        "code": "ai_issue",
        "severity": "warning",
        "message": "bounded issue",
        "field": "translation",
        "expected": "expected",
        "actual": "actual",
        "score_impact": 1,
    }
    issue[field_name] = oversized_value
    evaluator = _evaluator({"issues": [issue]})

    with pytest.raises(QualityEvaluationError) as excinfo:
        await evaluator.evaluate(source_text="hello", translated_text="hola")

    assert excinfo.value.code == "quality_ai_malformed_response"


@pytest.mark.asyncio
async def test_ai_quality_evaluator_rejects_oversized_raw_response_before_json_parse() -> None:
    evaluator = _evaluator(" " + ("x" * 262_145))

    with pytest.raises(QualityEvaluationError) as excinfo:
        await evaluator.evaluate(source_text="hello", translated_text="hola")

    assert excinfo.value.code == "quality_ai_malformed_response"
    assert "oversized" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_ai_quality_evaluator_accepts_values_at_bounds() -> None:
    issue = {
        "code": "quality_" + "x" * 92,
        "severity": "warning",
        "message": "m" * 1000,
        "field": "f" * 100,
        "expected": "e" * 2000,
        "actual": "a" * 2000,
        "score_impact": 1,
    }
    evaluator = _evaluator({"issues": [issue]})

    issues = await evaluator.evaluate(source_text="hello", translated_text="hola")

    assert len(issues) == 1
    assert len(issues[0].message) == 1000
    assert len(issues[0].expected or "") == 2000
