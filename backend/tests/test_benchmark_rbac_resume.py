from __future__ import annotations

from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from app.benchmarks.dataset import load_dataset
from app.core.security import create_access_token, hash_password
from app.dependencies.db import get_db
from app.main import app
from app.models import BenchmarkRun, User


@pytest.fixture
def benchmark_auth_client(async_session_factory):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


async def _create_editor(async_session_factory, *, email: str) -> User:
    async with async_session_factory() as session:
        user = User(
            email=email,
            password_hash=hash_password("some-password-1"),
            role="editor",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


def _auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.mark.asyncio
async def test_editor_can_resume_and_execute_dry_run_benchmark(
    benchmark_auth_client,
    async_session_factory,
) -> None:
    editor = await _create_editor(async_session_factory, email="editor-dry-resume@example.com")
    headers = _auth_header(editor)

    created = benchmark_auth_client.post(
        "/api/v1/benchmark-runs",
        json={"provider": "openai", "model": "gpt-4o", "max_cases": 1, "dry_run": True},
        headers=headers,
    )
    assert created.status_code == 202, created.text
    assert created.json()["status"] == "pending"

    resumed = benchmark_auth_client.post(
        f"/api/v1/benchmark-runs/{created.json()['run_id']}/resume",
        headers=headers,
    )
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["resumed"] is True


@pytest.mark.asyncio
async def test_editor_cannot_resume_live_provider_benchmark(
    benchmark_auth_client,
    async_session_factory,
) -> None:
    dataset = load_dataset()
    async with async_session_factory() as session:
        run = BenchmarkRun(
            run_id="bench-live-rbac-resume",
            dataset_name=dataset.name,
            dataset_version=dataset.version,
            dataset_checksum=dataset.checksum,
            provider="openai",
            model="gpt-4o",
            evaluator_version="1.0.0",
            status="pending",
            seed=0,
            concurrency=1,
            timeout_seconds=30,
            max_cases=1,
            max_retries=0,
            max_budget_usd=1.0,
            dry_run=False,
            confirm_live_provider=True,
            execution_contract={},
            pricing_snapshot={},
            metrics={},
            category_metrics={},
        )
        session.add(run)
        await session.commit()

    editor = await _create_editor(async_session_factory, email="editor-live-resume@example.com")
    response = benchmark_auth_client.post(
        "/api/v1/benchmark-runs/bench-live-rbac-resume/resume",
        headers=_auth_header(editor),
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "forbidden"
