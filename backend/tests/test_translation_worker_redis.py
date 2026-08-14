from __future__ import annotations

import pytest

from app.translation_queue.redis_stream import RedisStreamQueue


@pytest.mark.asyncio
async def test_redis_stream_queue_publish_and_read_group():
    class FakeRedis:
        def __init__(self):
            self.events = []
            self.messages = []

        async def xgroup_create(self, stream_name, group_name, id, mkstream):
            self.events.append(("group", stream_name, group_name, id, mkstream))

        async def xadd(self, stream_name, fields):
            self.messages.append((stream_name, fields))
            self.events.append(("add", stream_name, fields))
            return "1-0"

        async def xreadgroup(self, group_name, consumer_name, streams, count, block):
            self.events.append(("readgroup", group_name, consumer_name, streams, count, block))
            return []

        async def xack(self, stream_name, group_name, message_id):
            self.events.append(("ack", stream_name, group_name, message_id))
            return 1

    fake = FakeRedis()
    queue = RedisStreamQueue(redis_client=fake, stream_name="translation_jobs", consumer_group="translation-workers", consumer_name="c1")
    await queue.ensure_consumer_group()
    await queue.publish(job_id=10, segment_id=11, provider="deepl")
    await queue.read_group(count=5, block_ms=100)
    await queue.ack("1-0")
    assert any(item[0] == "group" for item in fake.events)
    assert any(item[0] == "add" for item in fake.events)
    assert any(item[0] == "ack" for item in fake.events)
