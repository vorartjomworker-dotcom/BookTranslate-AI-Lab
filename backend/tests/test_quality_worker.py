from __future__ import annotations

import asyncio

import pytest

from app.workers.translator_worker import TranslatorWorker


class FakeRedis:
    def __init__(self):
        self.xacked: list[str] = []

    async def xack(self, *args):
        self.xacked.append(args[2])
        return 1


async def _fake_sleep(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_worker_run_acks_completed_jobs(monkeypatch):
    worker = TranslatorWorker()
    worker.redis = FakeRedis()
    worker.should_exit = False

    async def fake_dispatch(*args, **kwargs):
        return 0

    async def fake_read_jobs():
        worker.should_exit = True
        return [{"id": "msg-1", "payload": {"job_id": "1", "segment_id": "1", "provider": "openai"}}]

    async def fake_reclaim_stale_jobs():
        return []

    monkeypatch.setattr(worker.dispatcher, "dispatch_pending", fake_dispatch)
    monkeypatch.setattr(worker, "_read_jobs", fake_read_jobs)
    monkeypatch.setattr(worker, "_reclaim_stale_jobs", fake_reclaim_stale_jobs)

    async def fake_process(*args, **kwargs):
        return {"status": "completed", "persistence_error": False}

    monkeypatch.setattr(worker, "process_translation_job", fake_process)
    monkeypatch.setattr("app.workers.translator_worker.asyncio.sleep", _fake_sleep)

    await worker.run()

    assert worker.redis.xacked == ["msg-1"]


@pytest.mark.asyncio
async def test_worker_run_does_not_ack_persistence_error(monkeypatch):
    worker = TranslatorWorker()
    worker.redis = FakeRedis()
    worker.should_exit = False

    async def fake_dispatch(*args, **kwargs):
        return 0

    async def fake_read_jobs():
        worker.should_exit = True
        return [{"id": "msg-2", "payload": {"job_id": "2", "segment_id": "2", "provider": "openai"}}]

    async def fake_reclaim_stale_jobs():
        return []

    monkeypatch.setattr(worker.dispatcher, "dispatch_pending", fake_dispatch)
    monkeypatch.setattr(worker, "_read_jobs", fake_read_jobs)
    monkeypatch.setattr(worker, "_reclaim_stale_jobs", fake_reclaim_stale_jobs)

    async def fake_process(*args, **kwargs):
        return {"status": "failed", "persistence_error": True}

    monkeypatch.setattr(worker, "process_translation_job", fake_process)
    monkeypatch.setattr("app.workers.translator_worker.asyncio.sleep", _fake_sleep)

    await worker.run()

    assert worker.redis.xacked == []


@pytest.mark.asyncio
async def test_worker_run_propagates_cancelled_error(monkeypatch):
    worker = TranslatorWorker()
    worker.redis = FakeRedis()
    worker.should_exit = False

    async def fake_dispatch(*args, **kwargs):
        return 0

    async def fake_read_jobs():
        worker.should_exit = True
        return [{"id": "msg-3", "payload": {"job_id": "3", "segment_id": "3", "provider": "openai"}}]

    async def fake_process(*args, **kwargs):
        raise asyncio.CancelledError()

    async def fake_reclaim_stale_jobs():
        return []

    monkeypatch.setattr(worker.dispatcher, "dispatch_pending", fake_dispatch)
    monkeypatch.setattr(worker, "_read_jobs", fake_read_jobs)
    monkeypatch.setattr(worker, "_reclaim_stale_jobs", fake_reclaim_stale_jobs)
    monkeypatch.setattr(worker, "process_translation_job", fake_process)
    monkeypatch.setattr("app.workers.translator_worker.asyncio.sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.run()
    assert worker.redis.xacked == []


@pytest.mark.asyncio
async def test_worker_process_translation_job_detects_duplicate_completed_jobs(monkeypatch):
    worker = TranslatorWorker()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, model, key, **_kwargs):
            if model.__name__ == "TranslationJob":
                return type("Job", (), {"status": "completed"})()
            if model.__name__ == "Segment":
                return type("Segment", (), {"qa_score": 91, "qa_status": "passed"})()
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

    monkeypatch.setattr("app.workers.translator_worker.async_session_factory", lambda: FakeSession())

    result = await worker.process_translation_job(segment_id=1, job_id=10)

    assert result["status"] == "completed"
    assert result["duplicate"] is True
    assert result["qa_score"] == 91


@pytest.mark.asyncio
async def test_worker_process_translation_job_completes_successful_translation(monkeypatch):
    worker = TranslatorWorker()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, model, key, **_kwargs):
            if model.__name__ == "TranslationJob":
                return type(
                    "Job",
                    (),
                    {
                        "status": "queued",
                        "provider": "openai",
                        "model": "gpt-4o",
                        "queued_at": None,
                        "started_at": None,
                        "error_message": None,
                    },
                )()
            if model.__name__ == "Segment":
                return type(
                    "Segment",
                    (),
                    {
                        "original_text": "hello",
                        "translated_text": None,
                        "model_used": None,
                        "confidence": 0.0,
                        "tokens_used": 0,
                        "latency_ms": 0,
                        "status": "pending",
                        "qa_score": 0,
                        "qa_status": "pending",
                        "qa_comment": "",
                    },
                )()
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

    class FakeTranslationService:
        async def translate(self, request):
            return type(
                "Result",
                (),
                {
                    "translated_text": "hola",
                    "provider": "openai",
                    "model": "gpt-4o",
                    "confidence": 0.9,
                    "total_tokens": 12,
                    "latency_ms": 30,
                },
            )()

    class FakeQualityService:
        async def evaluate_segment(self, *args, **kwargs):
            return type("Report", (), {"score": 90, "status": "passed", "overall_score": 90})()

    monkeypatch.setattr("app.workers.translator_worker.async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("app.workers.translator_worker.TranslationService", lambda settings_obj: FakeTranslationService())
    monkeypatch.setattr("app.workers.translator_worker.QualityAssuranceService", lambda session: FakeQualityService())

    result = await worker.process_translation_job(segment_id=1, job_id=20)

    assert result["status"] == "completed"
    assert result["provider"] == "openai"
    assert result["qa_score"] == 90
