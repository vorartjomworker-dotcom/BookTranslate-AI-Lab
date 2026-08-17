from __future__ import annotations

import pytest

from app.benchmarks.dataset import TECHNICAL_TRANSLATION_DATASET_VERSION
from app.benchmarks.service import BenchmarkService


@pytest.mark.asyncio
async def test_cancel_reason_redacts_credentials_before_persistence_and_export(async_session_factory) -> None:
    redis_password = "redis-password-do-not-store"
    query_token = "query-token-do-not-store"
    bearer_token = "bearer-token-do-not-store"
    api_key = "sk-do-not-store-this-api-key"
    reason = (
        "operator note: "
        f"redis://default:{redis_password}@cache.example:6379/0?token={query_token} "
        f"Authorization: Bearer {bearer_token} api_key={api_key}"
    )

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
        cancelled = await service.cancel_run(run.run_id, reason=reason)
        exported = await service.export_run(run.id, output_format="json")

    assert cancelled.status == "cancelled"
    assert cancelled.error_code == "benchmark_cancelled"
    assert cancelled.error_message is not None
    assert "<redacted>" in cancelled.error_message
    for secret in (redis_password, query_token, bearer_token, api_key):
        assert secret not in cancelled.error_message
        assert secret not in exported


@pytest.mark.asyncio
async def test_blank_cancel_reason_uses_safe_default(async_session_factory) -> None:
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
        cancelled = await service.cancel_run(run.run_id, reason="   ")

    assert cancelled.error_message == "Benchmark run cancelled by request."
