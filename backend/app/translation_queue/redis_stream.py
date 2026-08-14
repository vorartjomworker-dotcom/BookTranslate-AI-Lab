from __future__ import annotations

from typing import Any

from redis.asyncio import Redis

from app.translation_queue.contracts import TranslationQueueMessage


class RedisStreamQueue:
    def __init__(
        self,
        *,
        redis_client: Redis | None = None,
        stream_name: str = "translation_jobs",
        consumer_group: str = "translation-workers",
        consumer_name: str = "translator-worker-1",
        dlq_stream_name: str = "translation_jobs_dlq",
        block_ms: int = 5000,
        batch_size: int = 10,
        reclaim_idle_ms: int = 60000,
    ) -> None:
        self.redis = redis_client
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        self.dlq_stream_name = dlq_stream_name
        self.block_ms = block_ms
        self.batch_size = batch_size
        self.reclaim_idle_ms = reclaim_idle_ms

    async def ensure_consumer_group(self) -> None:
        if self.redis is None:
            raise RuntimeError("Redis client is not configured")
        try:
            await self.redis.xgroup_create(self.stream_name, self.consumer_group, id="0-0", mkstream=True)
        except Exception as exc:  # pragma: no cover - concurrent startup safety
            if "BUSYGROUP" not in str(exc):
                raise

    async def publish(self, *, job_id: int, segment_id: int, provider: str | None = None, model: str | None = None, attempt: int = 0, max_attempts: int = 3) -> str:
        if self.redis is None:
            raise RuntimeError("Redis client is not configured")
        message = TranslationQueueMessage(
            job_id=job_id,
            segment_id=segment_id,
            provider=provider,
            model=model,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        return await self.redis.xadd(self.stream_name, message.to_payload())

    async def read_group(self, *, count: int | None = None, block_ms: int | None = None) -> list[tuple[str, dict[str, Any]]]:
        if self.redis is None:
            return []
        response = await self.redis.xreadgroup(
            self.consumer_group,
            self.consumer_name,
            {self.stream_name: ">"},
            count=count or self.batch_size,
            block=block_ms or self.block_ms,
        )
        results: list[tuple[str, dict[str, Any]]] = []
        for _, items in response or []:
            for message_id, payload in items:
                results.append((message_id, dict(payload or {})))
        return results

    async def ack(self, message_id: str) -> int:
        if self.redis is None:
            return 0
        return await self.redis.xack(self.stream_name, self.consumer_group, message_id)

    async def reclaim_pending(self, *, idle_ms: int | None = None, consumer_name: str | None = None) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
        if self.redis is None:
            return "0-0", []
        result = await self.redis.xautoclaim(
            self.stream_name,
            self.consumer_group,
            consumer_name or self.consumer_name,
            min_idle_time=idle_ms or self.reclaim_idle_ms,
            start_id="0-0",
            count=self.batch_size,
        )
        if result is None:
            return "0-0", []

        if isinstance(result, tuple) and len(result) == 3:
            next_start, entries, _ = result
        elif isinstance(result, tuple) and len(result) >= 2:
            next_start, entries = result[:2]
        else:
            return "0-0", []

        parsed_entries: list[tuple[str, dict[str, Any]]] = []
        for item in entries or []:
            if isinstance(item, tuple) and len(item) == 2:
                message_id, payload = item
                parsed_entries.append((str(message_id), dict(payload or {})))
        return str(next_start), parsed_entries

    async def publish_dlq(self, *, payload: dict[str, Any], reason: str, message_id: str | None = None) -> str:
        if self.redis is None:
            raise RuntimeError("Redis client is not configured")
        data = {
            "reason": reason,
            "message_id": message_id or "",
            "job_id": str(payload.get("job_id", "")),
            "segment_id": str(payload.get("segment_id", "")),
        }
        return await self.redis.xadd(self.dlq_stream_name, data)
