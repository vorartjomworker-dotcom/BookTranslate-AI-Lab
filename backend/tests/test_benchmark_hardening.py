from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from app.benchmarks.dataset import TECHNICAL_TRANSLATION_DATASET_VERSION
from app.benchmarks.metrics import summarize_category_metrics
from app.benchmarks.pricing import get_pricing_snapshot
from app.benchmarks.service import BenchmarkService
from app.benchmarks.types import BenchmarkCaseResultModel
from app.core.exceptions import ConflictError, ValidationError
from app.dependencies.db import get_db
from app.main import app


@pytest.fixture
def benchmark_hardening_client(async_session_factory):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_unknown_provider_model_has_no_pricing_fallback() -> None:
    with pytest.raises(ValidationError):
        get_pricing_snapshot("unknown-provider", "unknown-model")
    with pytest.raises(ValidationError):
        get_pricing_snapshot("openai", "unknown-model")


def test_category_metrics_are_grouped_independently() -> None:
    metrics = summarize_category_metrics(
        [
            {"category": "technical", "status": "completed", "latency_ms": 10, "qa_score": 90, "qa_passed": True},
            {"category": "technical", "status": "failed", "latency_ms": 20, "qa_score": 0, "qa_passed": False},
            {"category": "urls", "status": "completed", "latency_ms": 30, "qa_score": 100, "qa_passed": True},
        ]
    )
    assert set(metrics) == {"technical", "urls"}
    assert metrics["technical"]["case_count"] == 2
    assert metrics["technical"]["success_rate"] == 50.0
    assert metrics["urls"]["case_count"] == 1
    assert metrics["urls"]["qa_pass_rate"] == 100.0


def test_invalid_provider_model_returns_422_with_matching_request_id(benchmark_hardening_client) -> None:
    response = benchmark_hardening_client.post(
        "/api/v1/benchmark-runs",
        json={"provider": "openai", "model": "invented-model", "dry_run": True},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_dry_run_honors_configured_concurrency(async_session_factory, monkeypatch) -> None:
    active = 0
    maximum_active = 0

    async def fake_run_case(self, *, case, **kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return BenchmarkCaseResultModel(
            case_id=case.case_id,
            category=case.category,
            status="completed",
            attempt_count=1,
            latency_ms=20,
            input_tokens=10,
            output_tokens=10,
            total_tokens=20,
            estimated_cost_usd=0.0002,
            qa_score=100,
            qa_passed=True,
        )

    monkeypatch.setattr("app.benchmarks.engine.BenchmarkExecutionEngine._run_case", fake_run_case)
    async with async_session_factory() as session:
        service = BenchmarkService(session)
        run = await service.create_run(
            provider="openai",
            model="gpt-4o",
            dataset_name="technical_translation",
            dataset_version=TECHNICAL_TRANSLATION_DATASET_VERSION,
            max_cases=3,
            concurrency=3,
            seed=1,
            timeout_seconds=30,
            max_retries=0,
            max_budget_usd=1.0,
            dry_run=True,
        )
        completed = await service.execute_run(run.run_id)

    assert completed.status == "completed"
    assert maximum_active >= 2
    assert len(completed.category_metrics) == 3


@pytest.mark.asyncio
async def test_zero_budget_fails_cases_without_overspend(async_session_factory) -> None:
    async with async_session_factory() as session:
        service = BenchmarkService(session)
        run = await service.create_run(
            provider="openai",
            model="gpt-4o",
            dataset_name="technical_translation",
            dataset_version=TECHNICAL_TRANSLATION_DATASET_VERSION,
            max_cases=2,
            concurrency=1,
            seed=1,
            timeout_seconds=30,
            max_retries=0,
            max_budget_usd=0.0,
            dry_run=True,
        )
        completed = await service.execute_run(run.run_id)
        cases = await service.get_case_results(run.id)

    assert completed.status == "partially_failed"
    assert cases and all(case.status == "failed" for case in cases)
    assert completed.metrics["total_estimated_cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_live_concurrency_is_rejected_to_preserve_budget_guard(async_session_factory) -> None:
    async with async_session_factory() as session:
        service = BenchmarkService(session)
        with pytest.raises(ValidationError):
            await service.create_run(
                provider="openai",
                model="gpt-4o",
                dataset_name="technical_translation",
                dataset_version=TECHNICAL_TRANSLATION_DATASET_VERSION,
                max_cases=2,
                concurrency=2,
                seed=1,
                timeout_seconds=30,
                max_retries=0,
                max_budget_usd=1.0,
                dry_run=False,
                confirm_live_provider=True,
            )


@pytest.mark.asyncio
async def test_cancelled_run_cannot_execute(async_session_factory) -> None:
    async with async_session_factory() as session:
        service = BenchmarkService(session)
        run = await service.create_run(
            provider="openai",
            model="gpt-4o",
            dataset_name="technical_translation",
            dataset_version=TECHNICAL_TRANSLATION_DATASET_VERSION,
            max_cases=1,
            concurrency=1,
            seed=1,
            timeout_seconds=30,
            max_retries=0,
            max_budget_usd=1.0,
            dry_run=True,
        )
        cancelled = await service.cancel_run(run.run_id, reason="test")
        assert cancelled.status == "cancelled"
        with pytest.raises(ConflictError):
            await service.execute_run(run.run_id)


def test_api_error_payload_does_not_leak_secrets(benchmark_hardening_client) -> None:
    secret = "sk-do-not-leak-this-value"
    response = benchmark_hardening_client.post(
        "/api/v1/benchmark-runs",
        json={"provider": secret, "model": secret, "dry_run": True},
    )
    assert response.status_code == 422
    rendered = response.text
    assert secret not in rendered
