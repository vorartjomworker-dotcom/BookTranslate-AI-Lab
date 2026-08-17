"""Redis Streams-based translator worker."""

from __future__ import annotations

import asyncio
import inspect
import logging
import signal
import sys
from typing import Any

from redis.asyncio import Redis

from app.ai.exceptions import TranslationError
from app.ai.translation_service import TranslationService
from app.ai.types import TranslationRequest
from app.core.config import settings
from app.core.redis_security import safe_redis_endpoint
from app.core.time import utc_now_naive
from app.db import async_session_factory
from app.models import Segment, TranslationJob
from app.quality.service import QualityAssuranceService
from app.translation_queue.dispatcher import TranslationJobDispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def ensure_stream_group(redis: Redis, stream_name: str, group_name: str) -> None:
    try:
        await redis.xgroup_create(stream_name, group_name, id="0-0", mkstream=True)
    except Exception as exc:  # pragma: no cover - defensive for concurrent startup
        message = str(exc)
        if "BUSYGROUP" not in message:
            raise


async def enqueue_translation_job(
    *,
    job_id: int,
    segment_id: int,
    provider: str | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    redis_client: Redis | None = None,
) -> dict[str, Any]:
    client = redis_client or Redis.from_url(settings.redis_url, decode_responses=True)
    stream_name = settings.translation_stream_name
    payload = {
        "job_id": str(job_id),
        "segment_id": str(segment_id),
        "provider": provider or settings.default_ai_provider,
        "source_language": (source_language or settings.default_source_language).lower(),
        "target_language": (target_language or settings.default_target_language).lower(),
    }
    try:
        entry_id = await client.xadd(stream_name, payload)
        await ensure_stream_group(client, stream_name, settings.translation_consumer_group)
        return {
            "job_id": job_id,
            "segment_id": segment_id,
            "stream": stream_name,
            "entry_id": entry_id,
            "status": "queued",
        }
    finally:
        if redis_client is None:
            await client.aclose()


class TranslatorWorker:
    """Background worker for processing translation jobs."""

    def __init__(self) -> None:
        self.redis: Redis | None = None
        self.should_exit = False
        self.dispatcher = TranslationJobDispatcher(session_factory=async_session_factory, redis_client=None)

    async def connect(self) -> None:
        if self.redis is None:
            logger.info("Connecting to Redis at %s", safe_redis_endpoint(settings.redis_url))
            self.redis = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
            )

        if hasattr(self.redis, "ping"):
            await self.redis.ping()

        self.dispatcher.redis_client = self.redis
        await ensure_stream_group(self.redis, settings.translation_stream_name, settings.translation_consumer_group)
        logger.info("Redis connection successful")

    async def disconnect(self) -> None:
        if self.redis and hasattr(self.redis, "aclose"):
            await self.redis.aclose()
            logger.info("Redis connection closed")

    async def _mark_job_state(self, *, job_id: int | None, status: str, error: str | None = None) -> None:
        if job_id is None:
            return
        try:
            async with async_session_factory() as session:
                job = await session.get(TranslationJob, job_id)
                if job is None:
                    return

                if status == "queued":
                    if getattr(job, "queued_at", None) is None:
                        job.queued_at = utc_now_naive()
                elif status == "running":
                    if getattr(job, "started_at", None) is None:
                        job.started_at = utc_now_naive()
                    if getattr(job, "queued_at", None) is None:
                        job.queued_at = utc_now_naive()
                elif status == "completed":
                    if getattr(job, "completed_at", None) is None:
                        job.completed_at = utc_now_naive()
                    job.error_code = None
                    job.error_message = None
                elif status == "failed":
                    if getattr(job, "failed_at", None) is None:
                        job.failed_at = utc_now_naive()
                    if getattr(job, "error_code", None) is None:
                        job.error_code = "worker_failed"

                job.status = status
                if error is not None:
                    job.error_message = error
                elif status != "failed":
                    job.error_message = None
                await session.commit()
        except Exception as exc:  # pragma: no cover - best effort update while DB is unavailable
            logger.warning("Could not persist translation job %s state=%s: %s", job_id, status, exc)

    async def process_translation_job(self, segment_id: int, job_id: int | None = None, **kwargs: Any) -> dict[str, Any]:
        """Process a single translation job by reading the segment and translating it."""
        logger.info("Processing translation job for segment %d (job_id=%s)", segment_id, job_id)

        provider = (kwargs.get("provider") or settings.default_ai_provider or "openai").strip().lower()
        source_language = (kwargs.get("source_language") or settings.default_source_language or "en").strip().lower()
        target_language = (kwargs.get("target_language") or settings.default_target_language or "ru").strip().lower()

        result: dict[str, Any] = {
            "job_id": job_id,
            "segment_id": segment_id,
            "status": "queued",
            "provider": provider,
        }

        try:
            if job_id is not None:
                await self._mark_job_state(job_id=job_id, status="queued")
                await self._mark_job_state(job_id=job_id, status="running")

            async with async_session_factory() as session:
                segment = await session.get(Segment, segment_id)
                if segment is None:
                    raise RuntimeError("segment not found")

                job = await session.get(TranslationJob, job_id) if job_id is not None else None

                # Duplicate delivery of an already-completed job: no re-translation, no second QA report.
                if job is not None and job.status == "completed":
                    return {
                        "job_id": job_id,
                        "segment_id": segment_id,
                        "status": "completed",
                        "provider": provider,
                        "duplicate": True,
                        "qa_score": segment.qa_score,
                        "qa_status": segment.qa_status,
                    }

                partial_result: dict[str, Any] = {
                    "job_id": job_id,
                    "segment_id": segment_id,
                    "status": "running",
                    "provider": provider,
                }

                # Step 1: AI translation. Provider/business failures are legitimate, non-retryable
                # outcomes here -- they are recorded and acknowledged, not treated as persistence errors.
                try:
                    service = TranslationService(settings_obj=settings)
                    result_model = await service.translate(
                        TranslationRequest(
                            text=segment.original_text,
                            source_language=source_language,
                            target_language=target_language,
                            provider=provider,
                            model=settings.default_ai_model,
                            profile="general",
                        )
                    )
                except asyncio.CancelledError:
                    raise
                except TranslationError as exc:
                    logger.warning("Translation failed for segment %s: %s", segment_id, exc)
                    await session.rollback()
                    try:
                        if job is not None:
                            job.status = "failed"
                            job.error_message = str(exc)
                            job.error_code = getattr(exc, "code", exc.__class__.__name__)
                            job.failed_at = utc_now_naive()
                            await session.commit()
                    except asyncio.CancelledError:
                        raise
                    except Exception as persistence_exc:  # pragma: no cover - real DB outage
                        logger.exception("Could not persist failed translation job %s", job_id)
                        await session.rollback()
                        partial_result.update({
                            "status": "failed",
                            "message": str(persistence_exc),
                            "error_code": persistence_exc.__class__.__name__,
                            "persistence_error": True,
                        })
                        result.update(partial_result)
                        return partial_result
                    partial_result.update({
                        "status": "failed",
                        "message": str(exc),
                        "error_code": getattr(exc, "code", exc.__class__.__name__),
                    })
                    result.update(partial_result)
                    return partial_result

                # Steps 2-4: update Segment -> QA report -> update TranslationJob, all in one
                # transaction. Any failure here (including QA persistence failures) rolls back and
                # is surfaced as a persistence error so the caller does not XACK the message.
                try:
                    segment.translated_text = result_model.translated_text
                    segment.model_used = result_model.model or provider
                    segment.confidence = result_model.confidence if result_model.confidence is not None else segment.confidence
                    segment.tokens_used = int(result_model.total_tokens or segment.tokens_used)
                    segment.latency_ms = int(result_model.latency_ms or segment.latency_ms)

                    quality_service = QualityAssuranceService(session)
                    quality_report = await quality_service.evaluate_segment(
                        segment_id,
                        source_text=segment.original_text,
                        translated_text=result_model.translated_text,
                        provider=provider,
                        model=result_model.model or settings.default_ai_model,
                        source_language=source_language,
                        target_language=target_language,
                        translation_job_id=job_id,
                    )

                    # A low/failed QA score is informational only; it never triggers an automatic
                    # (paid) retranslation. The job is considered complete once translated.
                    segment.status = "translated"
                    if job is not None:
                        job.status = "completed"
                        job.error_code = None
                        job.error_message = None
                        job.completed_at = utc_now_naive()

                    await session.commit()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Could not persist translation/QA result for segment %s", segment_id)
                    await session.rollback()
                    try:
                        await self._mark_job_state(job_id=job_id, status="failed", error=str(exc))
                    except Exception:  # pragma: no cover - best effort only
                        logger.warning("Could not record failure state for job %s", job_id)
                    partial_result.update({
                        "status": "failed",
                        "message": str(exc),
                        "error_code": getattr(exc, "code", exc.__class__.__name__),
                        "persistence_error": True,
                    })
                    result.update(partial_result)
                    return partial_result

                partial_result.update({
                    "status": "completed",
                    "translated_text": result_model.translated_text,
                    "provider": result_model.provider,
                    "model": result_model.model,
                    "tokens_used": result_model.total_tokens,
                    "latency_ms": result_model.latency_ms,
                    "qa_score": quality_report.score,
                    "qa_status": quality_report.status,
                })
                result.update(partial_result)
                return partial_result
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - DB connectivity safety net for unit tests / watchdogs
            logger.warning("Translation job could not reach the database: %s", exc)
            result.update({
                "status": "failed",
                "message": str(exc),
                "error_code": exc.__class__.__name__,
                "persistence_error": True,
            })
            if job_id is not None:
                await self._mark_job_state(job_id=job_id, status="failed", error=str(exc))
            return result

    def _handle_signal(self, signum: int, frame: Any) -> None:
        logger.info("Received signal %d, initiating graceful shutdown", signum)
        self.should_exit = True

    async def _read_jobs(self) -> list[dict[str, Any]]:
        if self.redis is None:
            return []
        stream_name = settings.translation_stream_name
        group_name = settings.translation_consumer_group
        consumer_name = settings.translation_consumer_name
        entries = await self.redis.xreadgroup(
            group_name,
            consumer_name,
            {stream_name: ">"},
            count=10,
            block=settings.translation_stream_block_ms,
        )
        results: list[dict[str, Any]] = []
        for _, message_list in entries or []:
            for message_id, payload in message_list:
                job_data = {"id": message_id, "payload": payload}
                job_payload = payload or {}
                try:
                    job_data["job_id"] = int(job_payload.get("job_id", 0) or 0)
                    job_data["segment_id"] = int(job_payload.get("segment_id", 0) or 0)
                    job_data["provider"] = job_payload.get("provider") or settings.default_ai_provider
                    job_data["source_language"] = job_payload.get("source_language") or settings.default_source_language
                    job_data["target_language"] = job_payload.get("target_language") or settings.default_target_language
                except (TypeError, ValueError):
                    job_data["job_id"] = 0
                    job_data["segment_id"] = 0
                results.append(job_data)
        return results

    async def _reclaim_stale_jobs(self) -> list[dict[str, Any]]:
        if self.redis is None:
            return []

        try:
            from app.translation_queue.redis_stream import RedisStreamQueue

            queue = RedisStreamQueue(
                redis_client=self.redis,
                stream_name=settings.translation_stream_name,
                consumer_group=settings.translation_consumer_group,
                consumer_name=settings.translation_consumer_name,
                reclaim_idle_ms=settings.translation_job_max_stale_ms,
            )
            _, entries = await queue.reclaim_pending(idle_ms=settings.translation_job_max_stale_ms)
        except Exception as exc:  # pragma: no cover - defensive for Redis failures during recovery
            logger.warning("Could not reclaim stale translation jobs: %s", exc)
            return []

        results: list[dict[str, Any]] = []
        for message_id, payload in entries:
            job_payload = payload or {}
            job_data = {"id": message_id, "payload": job_payload}
            try:
                job_data["job_id"] = int(job_payload.get("job_id", 0) or 0)
                job_data["segment_id"] = int(job_payload.get("segment_id", 0) or 0)
                job_data["provider"] = job_payload.get("provider") or settings.default_ai_provider
                job_data["source_language"] = job_payload.get("source_language") or settings.default_source_language
                job_data["target_language"] = job_payload.get("target_language") or settings.default_target_language
            except (TypeError, ValueError):
                job_data["job_id"] = 0
                job_data["segment_id"] = 0
            results.append(job_data)
        return results

    async def run(self) -> None:
        logger.info("Starting translator worker")
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        try:
            while not self.should_exit:
                try:
                    if self.redis is None:
                        await self.connect()
                    self.dispatcher.redis_client = self.redis
                    self.dispatcher.session_factory = async_session_factory
                    logger.info("Worker ready and listening for jobs")

                    dispatched = await self.dispatcher.dispatch_pending(batch_size=settings.translation_queue_batch_size)
                    if dispatched:
                        logger.info("Dispatched %s pending jobs to Redis", dispatched)

                    jobs = await self._reclaim_stale_jobs()
                    jobs.extend(await self._read_jobs())
                    if not jobs:
                        await asyncio.sleep(0.5)
                        continue
                    for job in jobs:
                        message_id = job["id"]
                        payload = job.get("payload") or {}
                        if not payload:
                            continue
                        try:
                            result = await self.process_translation_job(
                                segment_id=int(job.get("segment_id") or 0),
                                job_id=int(job.get("job_id") or 0) or None,
                                provider=payload.get("provider"),
                                source_language=payload.get("source_language"),
                                target_language=payload.get("target_language"),
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            logger.exception("Processing job %s failed; leaving message unacked for redelivery", message_id)
                            continue

                        should_ack = result.get("status") in {"completed", "failed"} and not result.get("persistence_error")
                        if self.redis is not None and message_id and should_ack:
                            await self.redis.xack(settings.translation_stream_name, settings.translation_consumer_group, message_id)
                        logger.info("Completed job: %s", result)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # pragma: no cover - worker loop safety net
                    logger.exception("Worker loop error: %s", exc)
                    await asyncio.sleep(2)
                    if self.redis is not None and isinstance(self.redis, Redis):
                        try:
                            await self.redis.close()
                        except Exception:
                            pass
                        self.redis = None
        finally:
            if self.redis is not None and isinstance(self.redis, Redis):
                await self.disconnect()
            logger.info("Translator worker stopped")

    async def main(self) -> None:
        try:
            await self.run()
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user")
        except Exception as exc:  # pragma: no cover - process-level safety
            logger.exception("Worker crashed: %s", exc)
            sys.exit(1)


async def main() -> None:
    worker = TranslatorWorker()
    await worker.main()


if __name__ == "__main__":
    asyncio.run(main())