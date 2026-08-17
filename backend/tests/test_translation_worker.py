from __future__ import annotations

import pytest

from app.models import Segment, TranslationJob
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
        translated_text = "hola"
        provider = "openai"
        model = "gpt-4o"
        confidence = 0.98
        total_tokens = 12
        latency_ms = 50

    class FakeService:
        async def translate(self, request):
            return FakeTranslationResult()

    class FakeQueryResult:
        def scalars(self):
            return self

        def first(self):
            return None

        def all(self):
            return []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            return FakeQueryResult()

        def add(self, obj):
            return None

        def add_all(self, objs):
            return None

        async def flush(self):
            return None

        async def delete(self, obj):
            return None

        async def get(self, model, key):
            if model.__name__ == "Segment":
                return type("Segment", (), {"original_text": "hello", "translated_text": None, "status": "pending", "model_used": None, "confidence": None, "tokens_used": None, "latency_ms": None, "qa_score": 0, "qa_status": "pending", "qa_comment": ""})()
            if model.__name__ == "TranslationJob":
                return type("TranslationJob", (), {"status": "running", "error_message": None, "error_code": None, "completed_at": None, "failed_at": None})()
            return None

        async def commit(self):
            return None

    class FakeSessionFactory:
        def __call__(self):
            return FakeSession()

    async def claim_job(_job_id: int) -> str:
        return "claimed"

    monkeypatch.setattr("app.workers.translator_worker.async_session_factory", FakeSessionFactory())
    monkeypatch.setattr("app.workers.translator_worker.TranslationService", lambda settings_obj: FakeService())
    monkeypatch.setattr(worker, "_claim_job_for_processing", claim_job)

    result = await worker.process_translation_job(segment_id=10, job_id=20)

    assert result["status"] == "completed"
    assert result["provider"] == "openai"


@pytest.mark.asyncio
async def test_completed_duplicate_job_never_reopens_or_calls_provider(async_session_factory, monkeypatch):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=91,
            original_text="already translated source",
            translated_text="already translated",
            status="translated",
            qa_score=97,
            qa_status="pass",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        job = TranslationJob(
            segment_id=segment.id,
            provider="openai",
            model="gpt-4o",
            status="completed",
            attempt=0,
            max_attempts=3,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        segment_id = segment.id
        job_id = job.id

    def fail_if_provider_is_constructed(*args, **kwargs):
        raise AssertionError("duplicate completed job must not call the AI provider")

    monkeypatch.setattr("app.workers.translator_worker.async_session_factory", async_session_factory)
    monkeypatch.setattr("app.workers.translator_worker.TranslationService", fail_if_provider_is_constructed)

    result = await TranslatorWorker().process_translation_job(segment_id=segment_id, job_id=job_id)

    assert result["status"] == "completed"
    assert result["duplicate"] is True
    assert result["qa_score"] == 97

    async with async_session_factory() as session:
        reloaded = await session.get(TranslationJob, job_id)
        assert reloaded is not None
        assert reloaded.status == "completed"
