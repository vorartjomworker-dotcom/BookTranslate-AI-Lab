from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.v1.translation_jobs as jobs_api
from app.main import app
from app.dependencies.db import get_db
from app.models import Segment, TranslationJob


class _FakeDBResult:
    def scalar_one_or_none(self):
        return None


class _FakeSession:
    def __init__(self):
        self.added = []

    async def get(self, model, key):
        if model is Segment:
            return SimpleNamespace(
                id=1,
                chapter_id=1,
                segment_number=1,
                original_text="Original text",
                translated_text=None,
                confidence=0.0,
                model_used=None,
                status="pending",
                qa_score=0,
                qa_status=None,
                qa_comment=None,
                translation_profile="general",
                tokens_used=0,
                latency_ms=0,
            )
        return None

    async def execute(self, stmt):
        return _FakeDBResult()

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        for obj in self.added:
            if isinstance(obj, TranslationJob):
                obj.id = 1
                obj.created_at = None
                obj.queued_at = None
                obj.started_at = None
                obj.completed_at = None
                obj.failed_at = None

    async def refresh(self, obj):
        if isinstance(obj, TranslationJob):
            obj.id = 1


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_db_override():
    session = _FakeSession()

    async def _fake_db():
        yield session

    app.dependency_overrides[get_db] = _fake_db
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_translation_job_create_returns_202_and_request_id(client: TestClient, fake_db_override):
    response = client.post("/api/v1/segments/1/translation-jobs", json={"provider": "openai"})
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending_enqueue"
    assert body["provider"] == "openai"
    assert response.headers.get("X-Request-ID")


def test_create_job_does_not_publish_to_redis(client: TestClient, fake_db_override, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Redis publish should not be called from API create path")

    monkeypatch.setattr(jobs_api, "Redis", SimpleNamespace(from_url=fail), raising=False)

    response = client.post("/api/v1/segments/1/translation-jobs", json={"provider": "openai"})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending_enqueue"


def test_create_job_succeeds_when_redis_is_unavailable(client: TestClient, fake_db_override, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(jobs_api, "Redis", SimpleNamespace(from_url=fail), raising=False)

    response = client.post("/api/v1/segments/1/translation-jobs", json={"provider": "openai"})

    assert response.status_code == 202
    assert response.json()["status"] == "pending_enqueue"


def test_manual_translation_patch_updates_only_translated_text(client: TestClient, fake_db_override):
    response = client.patch("/api/v1/segments/1", json={"translated_text": "Manual translation"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["translated_text"] == "Manual translation"
    assert payload["original_text"] == "Original text"
    assert payload["status"] in {"translated", "pending"}


def test_manual_translation_endpoint_updates_only_translated_text(client: TestClient, fake_db_override):
    response = client.patch("/api/v1/segments/1/translation", json={"translated_text": "Manual translation"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["translated_text"] == "Manual translation"
    assert payload["original_text"] == "Original text"
    assert payload["status"] in {"translated", "pending"}


def test_manual_translation_endpoint_rejects_unsafe_fields(client: TestClient, fake_db_override):
    response = client.patch(
        "/api/v1/segments/1/translation",
        json={"translated_text": "Manual translation", "original_text": "Hacked", "model_used": "ignored"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"


def test_manual_translation_patch_rejects_unsafe_fields(client: TestClient, fake_db_override):
    response = client.patch("/api/v1/segments/1", json={"translated_text": "Manual translation", "original_text": "Hacked", "model_used": "ignored"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
