from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.benchmarks.dataset import TECHNICAL_TRANSLATION_DATASET_VERSION
from app.benchmarks.service import BenchmarkService
from app.core.config import settings


pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION_TESTS"),
    reason="PostgreSQL benchmark integration tests run only in CI with RUN_INTEGRATION_TESTS=1",
)


def build_test_session_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    database_url = os.getenv("DATABASE_URL", settings.database_url)
    assert database_url.startswith("postgresql+asyncpg://")
    engine = create_async_engine(database_url, poolclass=NullPool)
    return engine, async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_benchmark_run_persists_cases_metrics_and_resume_in_postgres() -> None:
    engine, session_factory = build_test_session_factory()
    try:
        async with session_factory() as session:
            await session.execute(text("DELETE FROM benchmark_case_results"))
            await session.execute(text("DELETE FROM benchmark_runs"))
            await session.commit()

            service = BenchmarkService(session)
            run = await service.create_run(
                provider="openai",
                model="gpt-4o",
                dataset_name="technical_translation",
                dataset_version=TECHNICAL_TRANSLATION_DATASET_VERSION,
                max_cases=3,
                concurrency=3,
                seed=42,
                timeout_seconds=30,
                max_retries=0,
                max_budget_usd=1.0,
                dry_run=True,
            )
            completed = await service.execute_run(run.run_id)

            assert completed.status == "completed"
            assert completed.metrics["case_count"] == 3
            assert len(completed.category_metrics) == 3

            count = await session.execute(
                text("SELECT COUNT(*) FROM benchmark_case_results WHERE run_id = :run_id"),
                {"run_id": run.id},
            )
            assert count.scalar_one() == 3

            resumed = await service.resume_run(run.run_id)
            assert resumed.status == "completed"
            count_after_resume = await session.execute(
                text("SELECT COUNT(*) FROM benchmark_case_results WHERE run_id = :run_id"),
                {"run_id": run.id},
            )
            assert count_after_resume.scalar_one() == 3
    finally:
        await engine.dispose()
