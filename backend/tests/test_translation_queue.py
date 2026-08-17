from __future__ import annotations

from datetime import datetime

import pytest
from redis.asyncio import Redis

from app.models import Segment, TranslationJob
from app.translation_queue.dispatcher import TranslationJobDispatcher
from app.translation_queue.redis_stream import RedisStreamQueue


@pytest.mark.asyncio
async def test_redis_stream_queue_minimal_payload_and_group_creation(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.created = []
            self.messages = []

        async def xgroup_create(self, stream_name, group_name, id, mkstream):
            self.created.append((stream_name, group_name, id, mkstream))

        async def xadd(self, stream_name, fields):
            self.messages.append((stream_name, fields))
            return "1-0"

    fake = FakeRedis()
    queue = RedisStreamQueue(redis_client=fake, stream_name="translation_jobs", consumer_group="translation-workers")
    await queue.ensure_consumer_group()
    entry_id = await queue.publish(job_id=42, segment_id=7, provider="deepl", model="model-x")
    assert entry_id == "1-0"
    assert fake.created == [("translation_jobs", "translation-workers", "0-0", True)]
    assert fake.messages[0][1]["job_id"] == "42"
    assert fake.messages[0][1]["segment_id"] == "7"
    assert fake.messages[0][1]["provider"] == "deepl"


@pytest.mark.asyncio
async def test_dispatcher_moves_pending_job_to_queued(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=1,
            original_text="hello",
            translated_text=None,
            status="pending",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        job = TranslationJob(
            segment_id=segment.id,
            provider="openai",
            model="gpt-4o",
            status="pending_enqueue",
            attempt=0,
            max_attempts=3,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

    class FakeRedis:
        def __init__(self):
            self.events = []

        async def xadd(self, stream_name, fields):
            self.events.append((stream_name, fields))
            return "1-0"

        async def xgroup_create(self, *args, **kwargs):
            return None

    dispatcher = TranslationJobDispatcher(session_factory=async_session_factory, redis_client=FakeRedis(), batch_size=10)
    published = await dispatcher.dispatch_pending()

    assert published == 1
    async with async_session_factory() as session:
        reloaded = await session.get(TranslationJob, job.id)
        assert reloaded is not None
        assert reloaded.status == "queued"
        assert reloaded.stream_message_id == "1-0"
        assert reloaded.queued_at is not None


@pytest.mark.asyncio
async def test_dispatcher_leaves_job_pending_when_redis_fails(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=2,
            original_text="retry",
            translated_text=None,
            status="pending",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        job = TranslationJob(
            segment_id=segment.id,
            provider="openai",
            model="gpt-4o",
            status="pending_enqueue",
            attempt=0,
            max_attempts=3,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

    class FakeRedis:
        async def xadd(self, stream_name, fields):
            raise RuntimeError("redis outage")

        async def xgroup_create(self, *args, **kwargs):
            return None

    dispatcher = TranslationJobDispatcher(session_factory=async_session_factory, redis_client=FakeRedis(), batch_size=10)
    published = await dispatcher.dispatch_pending()

    assert published == 0
    async with async_session_factory() as session:
        reloaded = await session.get(TranslationJob, job.id)
        assert reloaded is not None
        assert reloaded.status == "pending_enqueue"
        assert reloaded.failed_at is None


@pytest.mark.asyncio
async def test_dispatcher_uses_minimal_payload(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(
            chapter_id=1,
            segment_number=3,
            original_text="payload",
            translated_text=None,
            status="pending",
        )
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        job = TranslationJob(
            segment_id=segment.id,
            provider="deepl",
            model="model-x",
            status="pending_enqueue",
            attempt=1,
            max_attempts=4,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

    captured = {}

    class FakeRedis:
        async def xadd(self, stream_name, fields):
            captured.update(fields)
            return "2-0"

        async def xgroup_create(self, *args, **kwargs):
            return None

    dispatcher = TranslationJobDispatcher(session_factory=async_session_factory, redis_client=FakeRedis(), batch_size=10)
    await dispatcher.dispatch_pending()

    assert set(captured) == {"job_id", "segment_id", "provider", "model", "attempt", "max_attempts"}
    assert captured["job_id"] == str(job.id)
    assert captured["segment_id"] == str(segment.id)


@pytest.mark.asyncio
async def test_dispatcher_commits_selected_batch_once():
    jobs = [
        TranslationJob(
            id=index,
            segment_id=index,
            provider="openai",
            model="gpt-4o",
            status="pending_enqueue",
            attempt=0,
            max_attempts=3,
            queued_at=None,
        )
        for index in (1, 2)
    ]

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return jobs

    class FakeSession:
        def __init__(self):
            self.commit_count = 0
            self.rollback_count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            return FakeResult()

        async def commit(self):
            self.commit_count += 1

        async def rollback(self):
            self.rollback_count += 1

    class FakeFactory:
        def __init__(self, session):
            self.session = session

        def __call__(self):
            return self.session

    class FakeRedis:
        def __init__(self):
            self.calls = 0

        async def xgroup_create(self, *args, **kwargs):
            return None

        async def xadd(self, stream_name, fields):
            self.calls += 1
            return f"{self.calls}-0"

    session = FakeSession()
    redis = FakeRedis()
    dispatcher = TranslationJobDispatcher(session_factory=FakeFactory(session), redis_client=redis, batch_size=10)

    published = await dispatcher.dispatch_pending()

    assert published == 2
    assert redis.calls == 2
    assert session.commit_count == 1
    assert session.rollback_count == 0
    assert [job.status for job in jobs] == ["queued", "queued"]


@pytest.mark.asyncio
async def test_reclaim_pending_handles_redis_xautoclaim_three_tuple():
    class FakeRedis:
        async def xautoclaim(self, stream_name, group_name, consumer_name, min_idle_time, start_id, count):
            return ("0-0", [("1-0", {"job_id": "11", "segment_id": "22"})], 0)

    queue = RedisStreamQueue(
        redis_client=FakeRedis(),
        stream_name="translation_jobs",
        consumer_group="translation-workers",
        consumer_name="worker-1",
    )

    next_start, entries = await queue.reclaim_pending(idle_ms=5000)

    assert next_start == "0-0"
    assert entries == [("1-0", {"job_id": "11", "segment_id": "22"})]
