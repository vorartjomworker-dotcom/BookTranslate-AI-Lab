from __future__ import annotations

import pytest

from app.models import Book, Chapter, Segment, TranslationJob
from app.workers.translator_worker import TranslatorWorker


@pytest.mark.asyncio
async def test_durable_job_overrides_conflicting_stream_segment_provider_and_model(
    async_session_factory,
    monkeypatch,
) -> None:
    async with async_session_factory() as session:
        book = Book(
            title="durable-worker-context",
            file_path="/tmp/durable-worker-context.epub",
            file_type="epub",
            language="en",
        )
        session.add(book)
        await session.flush()

        chapter = Chapter(
            book_id=book.id,
            chapter_number=1,
            title="durable context",
            content="durable context",
        )
        session.add(chapter)
        await session.flush()

        intended = Segment(
            chapter_id=chapter.id,
            segment_number=1,
            original_text="translate the durable segment",
            status="pending",
        )
        distractor = Segment(
            chapter_id=chapter.id,
            segment_number=2,
            original_text="do not translate this stream hint",
            status="pending",
        )
        session.add_all([intended, distractor])
        await session.flush()

        job = TranslationJob(
            segment_id=intended.id,
            provider="anthropic",
            model="durable-model-v1",
            status="queued",
            attempt=0,
            max_attempts=3,
        )
        session.add(job)
        await session.commit()

        intended_id = intended.id
        distractor_id = distractor.id
        job_id = job.id

    captured = {}

    class FakeTranslationService:
        async def translate(self, request):
            captured["request"] = request
            return type(
                "Result",
                (),
                {
                    "translated_text": "durable translation",
                    "provider": request.provider,
                    "model": request.model,
                    "confidence": 0.99,
                    "total_tokens": 12,
                    "latency_ms": 20,
                },
            )()

    class FakeQualityService:
        async def evaluate_segment(self, segment_id, **kwargs):
            captured["qa_segment_id"] = segment_id
            captured["qa_provider"] = kwargs.get("provider")
            captured["qa_model"] = kwargs.get("model")
            return type("Report", (), {"score": 96, "status": "pass"})()

    monkeypatch.setattr("app.workers.translator_worker.async_session_factory", async_session_factory)
    monkeypatch.setattr(
        "app.workers.translator_worker.TranslationService",
        lambda settings_obj: FakeTranslationService(),
    )
    monkeypatch.setattr(
        "app.workers.translator_worker.QualityAssuranceService",
        lambda session: FakeQualityService(),
    )

    result = await TranslatorWorker().process_translation_job(
        segment_id=distractor_id,
        job_id=job_id,
        provider="openai",
        model="stream-model-must-not-win",
        source_language="zz",
        target_language="yy",
    )

    request = captured["request"]
    assert request.text == "translate the durable segment"
    assert request.provider == "anthropic"
    assert request.model == "durable-model-v1"
    assert request.source_language == "en"
    assert request.target_language == "ru"
    assert result["segment_id"] == intended_id
    assert result["provider"] == "anthropic"
    assert captured["qa_segment_id"] == intended_id
    assert captured["qa_provider"] == "anthropic"
    assert captured["qa_model"] == "durable-model-v1"

    async with async_session_factory() as session:
        intended_row = await session.get(Segment, intended_id)
        distractor_row = await session.get(Segment, distractor_id)
        job_row = await session.get(TranslationJob, job_id)
        assert intended_row is not None
        assert distractor_row is not None
        assert job_row is not None
        assert intended_row.translated_text == "durable translation"
        assert intended_row.status == "translated"
        assert distractor_row.translated_text is None
        assert distractor_row.status == "pending"
        assert job_row.status == "completed"


@pytest.mark.asyncio
async def test_worker_discards_stream_message_without_durable_job_id(monkeypatch) -> None:
    worker = TranslatorWorker()
    worker.should_exit = False

    class FakeRedis:
        def __init__(self):
            self.acked = []

        async def xack(self, *args):
            self.acked.append(args[2])
            return 1

    worker.redis = FakeRedis()

    async def fake_dispatch(*args, **kwargs):
        return 0

    async def fake_reclaim():
        return []

    async def fake_read():
        worker.should_exit = True
        return [
            {
                "id": "malformed-1",
                "job_id": 0,
                "segment_id": 999,
                "payload": {
                    "segment_id": "999",
                    "provider": "openai",
                    "model": "untracked-paid-model",
                },
            }
        ]

    async def must_not_process(*args, **kwargs):
        raise AssertionError("malformed stream message must not reach translation processing")

    monkeypatch.setattr(worker.dispatcher, "dispatch_pending", fake_dispatch)
    monkeypatch.setattr(worker, "_reclaim_stale_jobs", fake_reclaim)
    monkeypatch.setattr(worker, "_read_jobs", fake_read)
    monkeypatch.setattr(worker, "process_translation_job", must_not_process)

    await worker.run()

    assert worker.redis.acked == ["malformed-1"]


@pytest.mark.asyncio
async def test_completed_duplicate_uses_durable_segment_not_stream_hint(
    async_session_factory,
    monkeypatch,
) -> None:
    async with async_session_factory() as session:
        book = Book(
            title="durable-completed-context",
            file_path="/tmp/durable-completed-context.epub",
            file_type="epub",
            language="en",
        )
        session.add(book)
        await session.flush()
        chapter = Chapter(
            book_id=book.id,
            chapter_number=1,
            title="completed context",
            content="completed context",
        )
        session.add(chapter)
        await session.flush()
        intended = Segment(
            chapter_id=chapter.id,
            segment_number=1,
            original_text="source",
            translated_text="done",
            status="translated",
            qa_score=97,
            qa_status="pass",
        )
        distractor = Segment(
            chapter_id=chapter.id,
            segment_number=2,
            original_text="other",
            translated_text="other translation",
            status="translated",
            qa_score=11,
            qa_status="fail",
        )
        session.add_all([intended, distractor])
        await session.flush()
        job = TranslationJob(
            segment_id=intended.id,
            provider="openai",
            model="gpt-4o",
            status="completed",
            attempt=0,
            max_attempts=3,
        )
        session.add(job)
        await session.commit()
        intended_id = intended.id
        distractor_id = distractor.id
        job_id = job.id

    def provider_must_not_be_constructed(*args, **kwargs):
        raise AssertionError("completed duplicate must never call a provider")

    monkeypatch.setattr("app.workers.translator_worker.async_session_factory", async_session_factory)
    monkeypatch.setattr(
        "app.workers.translator_worker.TranslationService",
        provider_must_not_be_constructed,
    )

    result = await TranslatorWorker().process_translation_job(
        segment_id=distractor_id,
        job_id=job_id,
        provider="anthropic",
        model="wrong-model",
    )

    assert result["status"] == "completed"
    assert result["duplicate"] is True
    assert result["segment_id"] == intended_id
    assert result["qa_score"] == 97
    assert result["qa_status"] == "pass"
