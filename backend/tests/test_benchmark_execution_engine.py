from __future__ import annotations

from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from app.benchmarks.dataset import (
    TECHNICAL_TRANSLATION_DATASET_CHECKSUM,
    TECHNICAL_TRANSLATION_DATASET_VERSION,
    load_dataset,
)
from app.benchmarks.service import BenchmarkService
from app.dependencies.db import get_db
from app.main import app


@pytest.fixture
def benchmark_client(async_session_factory):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_benchmark_dataset_is_versioned_and_stable(async_session_factory):
    dataset = load_dataset()

    assert dataset.version == TECHNICAL_TRANSLATION_DATASET_VERSION
    assert dataset.checksum == TECHNICAL_TRANSLATION_DATASET_CHECKSUM
    assert len(dataset.cases) >= 8
    assert {case.category for case in dataset.cases} >= {
        "technical",
        "terminology",
        "numbers_units",
        "placeholders",
        "urls",
        "markdown",
        "code",
        "tables",
        "long_context",
    }


@pytest.mark.asyncio
async def test_benchmark_service_runs_dry_run_and_tracks_case_results(async_session_factory):
    async with async_session_factory() as session:
        service = BenchmarkService(session)

        run = await service.create_run(
            provider="openai",
            model="gpt-4o",
            dataset_name="technical_translation",
            dataset_version=TECHNICAL_TRANSLATION_DATASET_VERSION,
            max_cases=2,
            concurrency=1,
            seed=42,
            timeout_seconds=30,
            max_budget_usd=0.5,
            dry_run=True,
            confirm_live_provider=False,
        )

        run = await service.execute_run(run.run_id)
        assert run.status in {"completed", "partially_failed", "failed"}

        cases = await service.get_case_results(run.id)
        assert len(cases) >= 1
        assert all(case.status in {"completed", "failed", "cancelled"} for case in cases)

        resumed = await service.resume_run(run.id)
        assert resumed.status in {"completed", "partially_failed", "failed"}


@pytest.mark.asyncio
async def test_benchmark_resume_reuses_failed_case_result(async_session_factory):
    async with async_session_factory() as session:
        service = BenchmarkService(session)
        run = await service.create_run(
            provider="openai",
            model="gpt-4o",
            dataset_name="technical_translation",
            dataset_version=TECHNICAL_TRANSLATION_DATASET_VERSION,
            max_cases=2,
            concurrency=1,
            seed=42,
            timeout_seconds=30,
            max_budget_usd=0.5,
            dry_run=True,
            confirm_live_provider=False,
        )
        run = await service.execute_run(run.run_id)
        original_cases = await service.get_case_results(run.id)
        original_cases[0].status = "failed"
        run.status = "partially_failed"
        await session.commit()

        resumed = await service.resume_run(run.run_id)
        resumed_cases = await service.get_case_results(run.id)

        assert resumed.status == "completed"
        assert len(resumed_cases) == len(original_cases)
        assert resumed_cases[0].status == "completed"
        assert resumed_cases[0].attempt_count == 2


def test_benchmark_api_runs_and_exports_dry_run(benchmark_client):
    create_response = benchmark_client.post(
        "/api/v1/benchmark-runs",
        json={
            "provider": "openai",
            "model": "gpt-4o",
            "max_cases": 2,
            "max_budget_usd": 0.5,
            "dry_run": True,
        },
    )
    assert create_response.status_code == 202, create_response.text
    run_id = create_response.json()["run_id"]

    resume_response = benchmark_client.post(f"/api/v1/benchmark-runs/{run_id}/resume")
    assert resume_response.status_code == 202, resume_response.text
    assert resume_response.json()["status"] == "completed"

    cases_response = benchmark_client.get(f"/api/v1/benchmark-runs/{run_id}/cases")
    assert cases_response.status_code == 200, cases_response.text
    assert len(cases_response.json()["items"]) == 2

    export_response = benchmark_client.get(f"/api/v1/benchmark-runs/{run_id}/export?format=json")
    assert export_response.status_code == 200, export_response.text
    assert export_response.json()["dataset_checksum"] == TECHNICAL_TRANSLATION_DATASET_CHECKSUM
    assert len(export_response.json()["cases"]) == 2
