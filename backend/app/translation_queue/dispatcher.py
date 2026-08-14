from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.db import async_session_factory
from app.models import TranslationJob
from app.translation_queue.redis_stream import RedisStreamQueue

logger = logging.getLogger(__name__)


class TranslationJobDispatcher:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker | None = None,
        redis_client: Redis | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.session_factory = session_factory or async_session_factory
        self.redis_client = redis_client
        self.batch_size = int(batch_size or settings.translation_queue_batch_size or 10)

    async def dispatch_pending(self, *, batch_size: int | None = None) -> int:
        limit = int(batch_size or self.batch_size or 10)
        if limit <= 0:
            return 0

        async with self.session_factory() as session:
            stmt = (
                select(TranslationJob)
                .where(TranslationJob.status == "pending_enqueue")
                .order_by(TranslationJob.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            jobs = list(result.scalars().all())

            if not jobs:
                return 0

            published = 0
            redis_client = self.redis_client
            owns_redis = False

            if redis_client is None:
                redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
                owns_redis = True

            queue = RedisStreamQueue(
                redis_client=redis_client,
                stream_name=settings.translation_stream_name,
                consumer_group=settings.translation_consumer_group,
                consumer_name=settings.translation_consumer_name,
            )

            try:
                await queue.ensure_consumer_group()
                for job in jobs:
                    if job.status != "pending_enqueue":
                        continue
                    try:
                        message_id = await queue.publish(
                            job_id=job.id,
                            segment_id=job.segment_id,
                            provider=job.provider,
                            model=job.model,
                            attempt=job.attempt,
                            max_attempts=job.max_attempts,
                        )
                    except Exception as exc:  # pragma: no cover - Redis outage is handled by retrying later
                        logger.warning("Could not dispatch translation job %s to Redis: %s", job.id, exc)
                        await session.rollback()
                        continue

                    job.stream_message_id = message_id
                    job.status = "queued"
                    job.queued_at = job.queued_at or datetime.utcnow()
                    await session.commit()
                    published += 1
            finally:
                if owns_redis and redis_client is not None:
                    await redis_client.aclose()

            return published
