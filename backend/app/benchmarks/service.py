from __future__ import annotations

import asyncio
import csv
import io
import json
import random
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.benchmarks.dataset import load_dataset
from app.benchmarks.engine import BenchmarkExecutionEngine
from app.benchmarks.metrics import summarize_case_metrics, summarize_category_metrics
from app.benchmarks.pricing import estimate_cost_usd, get_pricing_snapshot
from app.benchmarks.repository import BenchmarkRepository
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.time import utc_now_naive
from app.models import BenchmarkCaseResult, BenchmarkRun


def _utcnow() -> datetime:
    return utc_now_naive()


class BenchmarkService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = BenchmarkRepository(session)
        bind = session.bind
        if bind is None:
            raise RuntimeError("BenchmarkService requires a bound AsyncSession.")
        self._case_session_factory = async_sessionmaker(bind=bind, expire_on_commit=False)

    async def create_run(
        self,
        *,
        provider: str,
        model: str,
        dataset_name: str,
        dataset_version: str,
        max_cases: int,
        concurrency: int,
        seed: int,
        timeout_seconds: int,
        max_retries: int | None = None,
        max_budget_usd: float = 5.0,
        dry_run: bool = True,
        confirm_live_provider: bool = False,
    ) -> BenchmarkRun:
        dataset = load_dataset()
        if dataset_name != dataset.name:
            raise ValidationError("Unsupported dataset name.", details={"dataset_name": dataset_name, "expected": dataset.name})
        if dataset_version != dataset.version:
            raise ValidationError("Dataset version mismatch.", details={"requested": dataset_version, "actual": dataset.version})
        if max_cases <= 0 or max_cases > 50:
            raise ValidationError("max_cases must be between 1 and 50.", details={"max_cases": max_cases})
        if concurrency <= 0 or concurrency > 4:
            raise ValidationError("concurrency must be between 1 and 4.", details={"concurrency": concurrency})
        if not dry_run and concurrency != 1:
            raise ValidationError(
                "Live benchmark runs require concurrency=1 to preserve the strict budget guard.",
                details={"concurrency": concurrency},
            )
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValidationError("timeout_seconds must be between 1 and 300.", details={"timeout_seconds": timeout_seconds})
        max_retries_value = 2 if max_retries is None else max_retries
        if max_retries_value < 0 or max_retries_value > 5:
            raise ValidationError("max_retries must be between 0 and 5.", details={"max_retries": max_retries_value})
        if max_budget_usd < 0 or max_budget_usd > 100:
            raise ValidationError("max_budget_usd must be between 0 and 100.", details={"max_budget_usd": max_budget_usd})
        if not dry_run and not confirm_live_provider:
            raise ValidationError("Live provider execution requires explicit confirmation.", details={"dry_run": dry_run})
        if not dry_run and not getattr(settings, "benchmark_allow_live_provider", False):
            raise ValidationError("Live provider execution is disabled by default.", details={"benchmark_allow_live_provider": False})

        pricing_snapshot = get_pricing_snapshot(provider, model)
        run = BenchmarkRun(
            run_id=f"bench-{_utcnow().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}",
            dataset_name=dataset_name,
            dataset_version=dataset.version,
            dataset_checksum=dataset.checksum,
            provider=pricing_snapshot.provider,
            model=pricing_snapshot.model,
            evaluator_version="1.0.0",
            status="pending",
            seed=seed,
            concurrency=concurrency,
            timeout_seconds=timeout_seconds,
            max_cases=max_cases,
            max_retries=max_retries_value,
            max_budget_usd=max_budget_usd,
            dry_run=dry_run,
            confirm_live_provider=confirm_live_provider,
            execution_contract={},
            pricing_snapshot=pricing_snapshot.model_dump(),
            metrics={},
            category_metrics={},
        )
        await self.repository.create_run(run)
        await self.session.commit()
        return run

    async def get_run(self, run_id: str | int) -> BenchmarkRun:
        run = await self.repository.get_run_by_db_id(run_id) if isinstance(run_id, int) else await self.repository.get_run_by_id(run_id)
        if run is None:
            raise NotFoundError("benchmark run", run_id)
        return run

    async def list_runs(self, *, page: int, page_size: int) -> tuple[list[BenchmarkRun], int]:
        return await self.repository.list_runs(offset=(page - 1) * page_size, limit=page_size)

    @staticmethod
    def _record_payload(record: BenchmarkCaseResult) -> dict[str, Any]:
        return {
            "case_id": record.case_id,
            "category": record.category,
            "status": record.status,
            "latency_ms": record.latency_ms,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "total_tokens": record.total_tokens,
            "estimated_cost_usd": record.estimated_cost_usd,
            "qa_score": record.qa_score,
            "qa_passed": record.qa_passed,
        }

    @staticmethod
    def _dry_run_cost(provider: str, model: str, source_text: str) -> float:
        translated = f"[DRY-RUN] {source_text or ''}"
        input_tokens = max(len((source_text or "").split()), 10)
        output_tokens = max(len(translated.split()), 8)
        return estimate_cost_usd(get_pricing_snapshot(provider, model), input_tokens=input_tokens, output_tokens=output_tokens)

    async def _run_isolated_case(self, *, run_db_id: int, case: Any, budget_remaining: float, semaphore: asyncio.Semaphore) -> dict[str, Any]:
        async with semaphore:
            async with self._case_session_factory() as case_session:
                case_run = await case_session.get(BenchmarkRun, run_db_id)
                if case_run is None:
                    raise NotFoundError("benchmark run", run_db_id)
                engine = BenchmarkExecutionEngine(case_session, engine_id=case_run.run_id)
                try:
                    result = await engine._run_case(
                        case=case,
                        provider=case_run.provider,
                        model=case_run.model,
                        run=case_run,
                        timeout_seconds=case_run.timeout_seconds,
                        concurrency=case_run.concurrency,
                        dry_run=case_run.dry_run,
                        max_retries=case_run.max_retries,
                        budget_remaining=budget_remaining,
                    )
                    await case_session.commit()
                    return result.model_dump()
                except asyncio.CancelledError:
                    await case_session.rollback()
                    raise
                except Exception:
                    await case_session.rollback()
                    raise

    async def execute_run(self, run_id: str) -> BenchmarkRun:
        run = await self.get_run(run_id)
        dataset = load_dataset()
        if run.dataset_checksum != dataset.checksum:
            raise ValidationError("Dataset checksum mismatch.", details={"run_id": run.run_id})
        if run.status in {"completed", "failed", "cancelled"}:
            raise ConflictError("Benchmark run has already reached a terminal state.", details={"run_id": run.run_id, "status": run.status})

        run.status = "running"
        run.started_at = _utcnow()
        run.execution_contract = {
            "provider": run.provider,
            "model": run.model,
            "dataset_name": run.dataset_name,
            "dataset_version": run.dataset_version,
            "dataset_checksum": run.dataset_checksum,
            "seed": run.seed,
            "max_cases": run.max_cases,
            "concurrency": run.concurrency,
            "timeout_seconds": run.timeout_seconds,
            "max_retries": run.max_retries,
            "max_budget_usd": run.max_budget_usd,
            "dry_run": run.dry_run,
            "confirm_live_provider": run.confirm_live_provider,
            "executor_version": "1.1.0",
        }
        await self.session.commit()

        case_results: list[dict[str, Any]] = []
        pending: list[tuple[Any, float]] = []
        budget_remaining = float(run.max_budget_usd)
        for case in dataset.cases[: run.max_cases]:
            record = await self.repository.get_case_result(run.id, case.case_id)
            if record is not None and record.status == "completed":
                case_results.append(self._record_payload(record))
                budget_remaining = max(0.0, budget_remaining - float(record.estimated_cost_usd or 0.0))
                continue
            pending.append((case, budget_remaining))
            if run.dry_run:
                budget_remaining = max(0.0, budget_remaining - self._dry_run_cost(run.provider, run.model, case.source_text))

        if run.dry_run and run.concurrency > 1 and pending:
            semaphore = asyncio.Semaphore(run.concurrency)
            concurrent_results = await asyncio.gather(
                *(self._run_isolated_case(run_db_id=run.id, case=case, budget_remaining=remaining, semaphore=semaphore) for case, remaining in pending)
            )
            case_results.extend(concurrent_results)
        else:
            engine = BenchmarkExecutionEngine(self.session, engine_id=run.run_id)
            for case, remaining in pending:
                result = await engine._run_case(
                    case=case,
                    provider=run.provider,
                    model=run.model,
                    run=run,
                    timeout_seconds=run.timeout_seconds,
                    concurrency=run.concurrency,
                    dry_run=run.dry_run,
                    max_retries=run.max_retries,
                    budget_remaining=remaining,
                )
                case_results.append(result.model_dump())
                if result.status == "completed" and not run.dry_run:
                    budget_remaining = max(0.0, budget_remaining - float(result.estimated_cost_usd or 0.0))

        run.metrics = summarize_case_metrics(case_results)
        run.category_metrics = summarize_category_metrics(case_results)
        run.completed_at = _utcnow()
        run.status = "completed" if case_results and all(item["status"] == "completed" for item in case_results) else "partially_failed" if case_results else "failed"
        await self.session.commit()
        return run

    async def resume_run(self, run_id: str | int) -> BenchmarkRun:
        run = await self.get_run(run_id)
        if run.status in {"completed", "failed", "cancelled"}:
            return run
        return await self.execute_run(run.run_id)

    async def cancel_run(self, run_id: str, *, reason: str | None = None) -> BenchmarkRun:
        run = await self.get_run(run_id)
        if run.status in {"completed", "failed", "cancelled"}:
            raise ConflictError("Cannot cancel a terminal benchmark run.", details={"run_id": run_id, "status": run.status})
        run.status = "cancelled"
        run.cancelled_at = _utcnow()
        run.error_code = "benchmark_cancelled"
        run.error_message = reason or "Benchmark run cancelled by request."
        await self.session.commit()
        return run

    async def get_case_results(self, run_db_id: int) -> list[BenchmarkCaseResult]:
        return await self.repository.get_case_results(run_db_id)

    async def export_run(self, run_db_id: int, *, output_format: str = "json") -> str:
        run = await self.repository.get_run_by_db_id(run_db_id)
        if run is None:
            raise NotFoundError("benchmark run", run_db_id)
        cases = await self.repository.get_case_results(run_db_id)
        payload = {
            "run_id": run.run_id,
            "status": run.status,
            "provider": run.provider,
            "model": run.model,
            "dataset_name": run.dataset_name,
            "dataset_version": run.dataset_version,
            "dataset_checksum": run.dataset_checksum,
            "execution_contract": run.execution_contract,
            "pricing_snapshot": run.pricing_snapshot,
            "metrics": run.metrics,
            "category_metrics": run.category_metrics,
            "cases": [
                {
                    "id": case.id,
                    "case_id": case.case_id,
                    "category": case.category,
                    "status": case.status,
                    "attempt_count": case.attempt_count,
                    "latency_ms": case.latency_ms,
                    "input_tokens": case.input_tokens,
                    "output_tokens": case.output_tokens,
                    "total_tokens": case.total_tokens,
                    "estimated_cost_usd": case.estimated_cost_usd,
                    "qa_score": case.qa_score,
                    "qa_passed": case.qa_passed,
                    "error_code": case.error_code,
                    "error_message": case.error_message,
                    "created_at": case.created_at.isoformat() if case.created_at else None,
                    "completed_at": case.completed_at.isoformat() if case.completed_at else None,
                }
                for case in cases
            ],
        }
        if output_format == "csv":
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=["case_id", "category", "status", "attempt_count", "latency_ms", "input_tokens", "output_tokens", "total_tokens", "estimated_cost_usd", "qa_score", "qa_passed", "error_code"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(payload["cases"])
            return output.getvalue()
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
