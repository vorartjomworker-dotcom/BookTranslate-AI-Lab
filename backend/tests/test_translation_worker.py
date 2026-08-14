from __future__ import annotations

import pytest

from app.workers.translator_worker import TranslatorWorker


@pytest.mark.asyncio
async def test_worker_import_and_basic_context():
    worker = TranslatorWorker()
    assert worker is not None
    assert hasattr(worker, "run")
    assert hasattr(worker, "process_translation_job")


@pytest.mark.asyncio
async def test_worker_does_not_ack_when_database_is_unavailable(monkeypatch):
    worker = TranslatorWorker()
    worker.should_exit = False

    class FakeRedis:
        def __init__(self):
            self.acked = []

        async def xreadgroup(self, *args, **kwargs):
            return [("translation_jobs", [("1-0", {"job_id": "7", "segment_id": "8", "provider": "openai"})])]

        async def xack(self, *args, **kwargs):
            self.acked.append(args)
            return 1

    worker.redis = FakeRedis()
    monkeypatch.setattr("app.workers.translator_worker.async_session_factory", None)

    async def raise_db_error(*args, **kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(worker, "process_translation_job", raise_db_error)
    monkeypatch.setattr(worker, "_reclaim_stale_jobs", lambda: [])

    async def stop_after_one_loop():
        worker.should_exit = True

    monkeypatch.setattr("asyncio.sleep", lambda *_args, **_kwargs: stop_after_one_loop())

    await worker.run()

    assert worker.redis.acked == []


@pytest.mark.asyncio
async def test_process_translation_job_uses_default_ai_provider(monkeypatch):
    worker = TranslatorWorker()

    class FakeTranslationResult:
        translated_text = "hello"
        provider = "openai"
        model = "gpt-4o"
        confidence = 0.98
        total_tokens = 12
        latency_ms = 50

    class FakeService:
        async def translate(self, request):
            return FakeTranslationResult()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, model, key):
            if model.__name__ == "Segment":
                return type("Segment", (), {"original_text": "hello", "translated_text": None, "status": "pending", "model_used": None, "confidence": None, "tokens_used": None, "latency_ms": None})()
            if model.__name__ == "TranslationJob":
                return type("TranslationJob", (), {"status": "queued", "error_message": None, "error_code": None, "completed_at": None, "failed_at": None})()
            return None

        async def commit(self):
            return None

    class FakeSessionFactory:
        def __call__(self):
            return FakeSession()

    monkeypatch.setattr("app.workers.translator_worker.async_session_factory", FakeSessionFactory())
    monkeypatch.setattr("app.workers.translator_worker.TranslationService", lambda settings_obj: FakeService())

    result = await worker.process_translation_job(segment_id=10, job_id=20)

    assert result["status"] == "completed"
    assert result["provider"] == "openai"
