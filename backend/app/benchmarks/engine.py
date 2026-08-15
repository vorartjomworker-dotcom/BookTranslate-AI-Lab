from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.exceptions import TranslationError
from app.ai.translation_service import TranslationService
from app.ai.types import TranslationRequest
from app.benchmarks.dataset import load_dataset
from app.benchmarks.metrics import summarize_case_metrics, summarize_category_metrics
from app.benchmarks.pricing import estimate_cost_usd, get_pricing_snapshot
from app.benchmarks.types import BenchmarkExecutionContract, BenchmarkCase, BenchmarkCaseResultModel
from app.core.config import settings
from app.core.exceptions import ConflictError, ValidationError
from app.models import BenchmarkCaseResult, BenchmarkRun
from app.quality.deterministic import DeterministicQualityEvaluator

logger = logging.getLogger(__name__)


def _safe_benchmark_error_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return exc.message
    if isinstance(exc, TranslationError):
        return "Benchmark provider request failed."
    return "Benchmark case execution failed."


class FakeBenchmarkProvider:
    def __init__(self, *, provider: str, model: str, latency_ms: int = 120, error_code: str | None = None) -> None:
        self.name = provider
        self.model = model
        self.latency_ms = latency_ms
        self.error_code = error_code

    async def translate(self, request: TranslationRequest) -> Any:
        if self.error_code == "provider_timeout_error":
            raise TranslationError("provider timeout", code="provider_timeout_error", provider=self.name, retryable=True)
        if self.error_code == "provider_quota_exceeded_error":
            raise TranslationError("quota exceeded", code="provider_quota_exceeded_error", provider=self.name, retryable=False)
        if self.error_code == "invalid_translation_response_error":
            raise TranslationError("malformed response", code="invalid_translation_response_error", provider=self.name, retryable=False)

        base = request.text.strip()
        translated = base
        if request.target_language.lower() == "ru":
            translated = f"[RU] {base}"
        return type(
            "FakeResult",
            (),
            {
                "translated_text": translated,
                "provider": self.name,
                "model": self.model,
                "source_language": request.source_language,
                "target_language": request.target_language,
                "input_tokens": max(10, len(base.split())),
                "output_tokens": max(8, len(translated.split())),
                "total_tokens": max(18, len(base.split()) + len(translated.split())),
                "latency_ms": self.latency_ms,
                "confidence": 0.99,
                "finish_reason": "stop",
            },
        )()


class BenchmarkExecutionEngine:
    def __init__(self, session: AsyncSession, *, engine_id: str | None = None) -> None:
        self.session = session
        self.engine_id = engine_id or hashlib.sha256(f"{datetime.utcnow().isoformat()}-{random.random()}".encode("utf-8")).hexdigest()[:12]
        self.deterministic_evaluator = DeterministicQualityEvaluator()

    def _normalise_provider_model(self, provider: str, model: str | None) -> tuple[str, str]:
        provider_name = (provider or settings.default_ai_provider or "openai").strip().lower()
        model_name = (model or settings.default_ai_model or "gpt-4o").strip()
        return provider_name, model_name

    @staticmethod
    def _hash_case(case: BenchmarkCase) -> str:
        payload = json.dumps(
            {
                "case_id": case.case_id,
                "category": case.category,
                "source_language": case.source_language,
                "target_language": case.target_language,
                "source_text": case.source_text,
                "reference_translation": case.reference_translation,
                "protected_tokens": case.protected_tokens,
                "metadata": case.metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def _preflight_budget(self, *, provider: str, model: str | None, max_budget_usd: float, dry_run: bool, confirm_live_provider: bool) -> None:
        provider_name, model_name = self._normalise_provider_model(provider, model)
        if dry_run:
            return
        if not confirm_live_provider:
            raise ValidationError("Live provider execution requires explicit confirmation.", details={"provider": provider_name, "model": model_name})
        if max_budget_usd <= 0:
            raise ValidationError("max_budget_usd must be positive for live runs.", details={"max_budget_usd": max_budget_usd})
        if not getattr(settings, "benchmark_allow_live_provider", False):
            raise ValidationError("Live benchmark provider execution is disabled by default.", details={"benchmark_allow_live_provider": False})
        if not getattr(settings, f"{provider_name}_api_key", ""):
            raise ValidationError("API key is required for live provider execution.", details={"provider": provider_name, "model": model_name})
        provider_api_key = getattr(settings, f"{provider_name}_api_key", "")
        if not provider_api_key or provider_api_key.startswith("sk-") is False and provider_name == "openai":
            raise ValidationError("OpenAI API key format is invalid.", details={"provider": provider_name})

    async def _resolve_provider(self, provider: str, model: str | None, *, dry_run: bool, max_retries: int):
        provider_name, model_name = self._normalise_provider_model(provider, model)
        if dry_run:
            return FakeBenchmarkProvider(provider=provider_name, model=model_name)
        return TranslationService(settings_obj=settings, max_retries=max_retries)

    async def _run_case(self, *, case: BenchmarkCase, provider: str, model: str | None, run: BenchmarkRun, timeout_seconds: int, concurrency: int, dry_run: bool, max_retries: int, budget_remaining: float) -> BenchmarkCaseResultModel:
        provider_name, model_name = self._normalise_provider_model(provider, model)
        record_query = select(BenchmarkCaseResult).where(
            BenchmarkCaseResult.run_id == run.id,
            BenchmarkCaseResult.case_id == case.case_id,
        )
        record = (await self.session.execute(record_query)).scalar_one_or_none()
        if record is None:
            record = BenchmarkCaseResult(
                run_id=run.id,
                case_id=case.case_id,
                category=case.category,
                status="pending",
                attempt_count=0,
                latency_ms=0,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                estimated_cost_usd=0.0,
                qa_score=0.0,
                qa_passed=False,
                error_code=None,
                error_message=None,
            )
            self.session.add(record)
            await self.session.flush()

        started = datetime.now(timezone.utc)
        record.status = "running"
        record.started_at = started
        record.completed_at = None
        record.error_code = None
        record.error_message = None
        record.attempt_count += 1
        await self.session.flush()

        try:
            if dry_run:
                source = case.source_text or ""
                translated = f"[DRY-RUN] {source}"
                input_tokens = max(len(source.split()), 10)
                output_tokens = max(len(translated.split()), 8)
                total_tokens = input_tokens + output_tokens
                snapshot = get_pricing_snapshot(provider_name, model_name)
                estimated_cost_usd = estimate_cost_usd(snapshot, input_tokens=input_tokens, output_tokens=output_tokens)
                if budget_remaining <= 0:
                    raise ValidationError("Benchmark budget exhausted before running this case.", details={"budget_remaining_usd": budget_remaining})
                if estimated_cost_usd > budget_remaining:
                    raise ValidationError("Case exceeds remaining benchmark budget.", details={"case_id": case.case_id, "budget_remaining_usd": budget_remaining, "estimated_cost_usd": estimated_cost_usd})
                score, issues = self.deterministic_evaluator.evaluate(source_text=case.source_text, translated_text=translated, source_language=case.source_language, target_language=case.target_language)
                record.latency_ms = 80
                record.input_tokens = input_tokens
                record.output_tokens = output_tokens
                record.total_tokens = total_tokens
                record.estimated_cost_usd = estimated_cost_usd
                record.qa_score = float(score)
                record.qa_passed = score >= 80
                record.status = "completed"
                record.completed_at = datetime.now(timezone.utc)
                await self.session.flush()
                return BenchmarkCaseResultModel(
                    case_id=case.case_id,
                    category=case.category,
                    status="completed",
                    attempt_count=record.attempt_count,
                    latency_ms=record.latency_ms,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    total_tokens=record.total_tokens,
                    estimated_cost_usd=record.estimated_cost_usd,
                    qa_score=record.qa_score,
                    qa_passed=record.qa_passed,
                    started_at=record.started_at.isoformat() if record.started_at else None,
                    completed_at=record.completed_at.isoformat() if record.completed_at else None,
                )

            provider_instance = await self._resolve_provider(
                provider_name,
                model_name,
                dry_run=False,
                max_retries=max_retries,
            )
            request = TranslationRequest(
                text=case.source_text,
                source_language=case.source_language,
                target_language=case.target_language,
                provider=provider_name,
                model=model_name,
                profile="technical",
            )
            result = await asyncio.wait_for(provider_instance.translate(request), timeout=timeout_seconds)
            score, issues = self.deterministic_evaluator.evaluate(source_text=case.source_text, translated_text=result.translated_text, source_language=case.source_language, target_language=case.target_language)
            snapshot = get_pricing_snapshot(provider_name, model_name)
            estimated_cost_usd = estimate_cost_usd(snapshot, input_tokens=int(result.input_tokens), output_tokens=int(result.output_tokens))
            if estimated_cost_usd > budget_remaining:
                raise ValidationError("Case exceeds remaining benchmark budget.", details={"case_id": case.case_id, "budget_remaining_usd": budget_remaining, "estimated_cost_usd": estimated_cost_usd})
            record.status = "completed"
            record.latency_ms = int(result.latency_ms or 0)
            record.input_tokens = int(result.input_tokens or 0)
            record.output_tokens = int(result.output_tokens or 0)
            record.total_tokens = int(result.total_tokens or record.input_tokens + record.output_tokens)
            record.estimated_cost_usd = estimated_cost_usd
            record.qa_score = float(score)
            record.qa_passed = score >= 80
            record.completed_at = datetime.now(timezone.utc)
            await self.session.flush()
            return BenchmarkCaseResultModel(
                case_id=case.case_id,
                category=case.category,
                status="completed",
                attempt_count=record.attempt_count,
                latency_ms=record.latency_ms,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                total_tokens=record.total_tokens,
                estimated_cost_usd=record.estimated_cost_usd,
                qa_score=record.qa_score,
                qa_passed=record.qa_passed,
                started_at=record.started_at.isoformat() if record.started_at else None,
                completed_at=record.completed_at.isoformat() if record.completed_at else None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error_code = getattr(exc, "code", exc.__class__.__name__)
            record.error_code = error_code
            safe_message = _safe_benchmark_error_message(exc)

            record.error_message = safe_message
            record.status = "failed"
            record.completed_at = datetime.now(timezone.utc)
            await self.session.flush()
            return BenchmarkCaseResultModel(
                case_id=case.case_id,
                category=case.category,
                status="failed",
                attempt_count=record.attempt_count,
                latency_ms=record.latency_ms,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                total_tokens=record.total_tokens,
                estimated_cost_usd=record.estimated_cost_usd,
                qa_score=record.qa_score,
                qa_passed=False,
                error_code=error_code,
                error_message=safe_message,
                started_at=record.started_at.isoformat() if record.started_at else None,
                completed_at=record.completed_at.isoformat() if record.completed_at else None,
            )

    async def execute_run(self, db_run: BenchmarkRun, *, dataset_cases: list[BenchmarkCase]) -> BenchmarkRun:
        if db_run.status in {"completed", "failed", "cancelled"}:
            raise ConflictError("This benchmark run is already terminal.", details={"run_id": db_run.run_id, "status": db_run.status})

        db_run.status = "running"
        db_run.started_at = datetime.now(timezone.utc)
        db_run.execution_contract = {
            "provider": db_run.provider,
            "model": db_run.model,
            "dataset_name": db_run.dataset_name,
            "dataset_version": db_run.dataset_version,
            "dataset_checksum": db_run.dataset_checksum,
            "seed": db_run.seed,
            "max_cases": db_run.max_cases,
            "concurrency": db_run.concurrency,
            "timeout_seconds": db_run.timeout_seconds,
            "max_retries": db_run.max_retries,
            "max_budget_usd": db_run.max_budget_usd,
            "dry_run": db_run.dry_run,
            "confirm_live_provider": db_run.confirm_live_provider,
            "executor_version": "1.0.0",
        }
        await self.session.flush()

        cases_to_run = dataset_cases[: db_run.max_cases]
        budget_remaining = float(db_run.max_budget_usd)
        case_results: list[dict[str, Any]] = []
        for case in cases_to_run:
            result = await self._run_case(
                case=case,
                provider=db_run.provider,
                model=db_run.model,
                run=db_run,
                timeout_seconds=db_run.timeout_seconds,
                concurrency=db_run.concurrency,
                dry_run=db_run.dry_run,
                max_retries=db_run.max_retries,
                budget_remaining=budget_remaining,
            )
            case_results.append(result.model_dump())
            if result.status == "completed":
                budget_remaining = max(0.0, budget_remaining - float(result.estimated_cost_usd or 0.0))
            if result.status == "failed" and db_run.max_budget_usd > 0 and budget_remaining <= 0:
                db_run.status = "partially_failed"
                break

        aggregate = summarize_case_metrics(case_results)
        db_run.metrics = aggregate
        db_run.category_metrics = summarize_category_metrics(case_results)
        db_run.completed_at = datetime.now(timezone.utc)
        db_run.status = "completed" if all(item["status"] == "completed" for item in case_results) else "partially_failed" if case_results else "failed"
        if not case_results:
            db_run.status = "failed"
        await self.session.flush()
        return db_run


async def build_run_from_request(session: AsyncSession, *, request: BenchmarkExecutionContract) -> BenchmarkRun:
    dataset = load_dataset()
    if request.dataset_version != dataset.version:
        raise ValidationError("Dataset version mismatch.", details={"requested": request.dataset_version, "actual": dataset.version})
    if request.dataset_checksum != dataset.checksum:
        raise ValidationError("Dataset checksum mismatch.", details={"requested": request.dataset_checksum, "actual": dataset.checksum})

    run = BenchmarkRun(
        run_id=f"bench-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}",
        dataset_name=request.dataset_name,
        dataset_version=request.dataset_version,
        dataset_checksum=request.dataset_checksum,
        provider=request.provider,
        model=request.model,
        evaluator_version=request.executor_version,
        status="pending",
        seed=request.seed,
        concurrency=request.concurrency,
        timeout_seconds=request.timeout_seconds,
        max_cases=request.max_cases,
        max_retries=request.max_retries,
        max_budget_usd=request.max_budget_usd,
        dry_run=request.dry_run,
        confirm_live_provider=request.confirm_live_provider,
        execution_contract=request.model_dump(),
        pricing_snapshot=get_pricing_snapshot(request.provider, request.model).model_dump(),
        metrics={},
        category_metrics={},
    )
    session.add(run)
    await session.flush()
    return run
