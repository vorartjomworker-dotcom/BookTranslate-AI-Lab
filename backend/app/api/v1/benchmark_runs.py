from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditService
from app.benchmarks.dataset import TECHNICAL_TRANSLATION_DATASET_CHECKSUM, TECHNICAL_TRANSLATION_DATASET_VERSION, load_dataset
from app.benchmarks.service import BenchmarkService
from app.core.exceptions import AuthorizationError, ConflictError, ValidationError
from app.core.pagination import MAX_PAGE_SIZE, build_paginated_response, normalize_pagination
from app.core.roles import ADMIN_ROLES, EDITOR_ROLES
from app.dependencies.auth import get_current_user, require_roles
from app.dependencies.db import get_db
from app.models import User

router = APIRouter(prefix="/api/v1", tags=["benchmark-runs"])


class BenchmarkRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., min_length=1, max_length=50)
    model: str = Field(..., min_length=1, max_length=100)
    dataset_name: str = Field(default="technical_translation", min_length=1, max_length=120)
    dataset_version: str = Field(default=TECHNICAL_TRANSLATION_DATASET_VERSION, min_length=1, max_length=50)
    dataset_checksum: str = Field(default=TECHNICAL_TRANSLATION_DATASET_CHECKSUM, min_length=1, max_length=64)
    max_cases: int = Field(default=10, ge=1, le=50)
    concurrency: int = Field(default=1, ge=1, le=4)
    seed: int = Field(default=0, ge=0)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_budget_usd: float = Field(default=5.0, ge=0.0, le=100.0)
    dry_run: bool = True
    confirm_live_provider: bool = False


class BenchmarkRunCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


@router.post("/benchmark-runs", status_code=status.HTTP_202_ACCEPTED)
async def create_benchmark_run(
    payload: BenchmarkRunCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
) -> dict[str, Any]:
    if user.role != "admin" and (not payload.dry_run or payload.confirm_live_provider):
        raise AuthorizationError("Only administrators may run live provider benchmarks.")
    dataset = load_dataset()
    if payload.dataset_name != dataset.name:
        raise ValidationError("Unsupported dataset name.", details={"dataset_name": payload.dataset_name, "expected": dataset.name})
    if payload.dataset_version != dataset.version:
        raise ValidationError("Dataset version mismatch.", details={"requested": payload.dataset_version, "actual": dataset.version})
    if payload.dataset_checksum != dataset.checksum:
        raise ValidationError("Dataset checksum mismatch.", details={"requested": payload.dataset_checksum, "actual": dataset.checksum})

    await AuditService(db).record(
        action="benchmark.create",
        outcome="success",
        actor_user_id=user.id,
        target_type="benchmark_run",
        request_id=getattr(request.state, "request_id", None),
        details={
            "provider": payload.provider,
            "model": payload.model,
            "dry_run": payload.dry_run,
            "dataset_version": payload.dataset_version,
        },
    )

    service = BenchmarkService(db)
    run = await service.create_run(
        provider=payload.provider,
        model=payload.model,
        dataset_name=payload.dataset_name,
        dataset_version=payload.dataset_version,
        max_cases=payload.max_cases,
        concurrency=payload.concurrency,
        seed=payload.seed,
        timeout_seconds=payload.timeout_seconds,
        max_retries=payload.max_retries,
        max_budget_usd=payload.max_budget_usd,
        dry_run=payload.dry_run,
        confirm_live_provider=payload.confirm_live_provider,
    )
    return {"run_id": run.run_id, "status": run.status, "dry_run": run.dry_run, "dataset_version": run.dataset_version, "dataset_checksum": run.dataset_checksum}


@router.get("/benchmark-runs", response_model=dict[str, Any])
async def list_benchmark_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    service = BenchmarkService(db)
    page, page_size = normalize_pagination(page, page_size)
    runs, total = await service.list_runs(page=page, page_size=page_size)
    return build_paginated_response(
        [
            {
                "run_id": run.run_id,
                "dataset_name": run.dataset_name,
                "dataset_version": run.dataset_version,
                "dataset_checksum": run.dataset_checksum,
                "provider": run.provider,
                "model": run.model,
                "status": run.status,
                "dry_run": run.dry_run,
                "created_at": run.created_at.isoformat() if run.created_at else None,
            }
            for run in runs
        ],
        total,
        page=page,
        page_size=page_size,
    )


@router.get("/benchmark-runs/{run_id}", response_model=dict[str, Any])
async def get_benchmark_run(run_id: str, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    service = BenchmarkService(db)
    run = await service.get_run(run_id)
    return {
        "run_id": run.run_id,
        "status": run.status,
        "provider": run.provider,
        "model": run.model,
        "dataset_name": run.dataset_name,
        "dataset_version": run.dataset_version,
        "dataset_checksum": run.dataset_checksum,
        "dry_run": run.dry_run,
        "metrics": run.metrics,
        "category_metrics": run.category_metrics,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


@router.get("/benchmark-runs/{run_id}/cases", response_model=dict[str, Any])
async def get_benchmark_cases(run_id: str, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    service = BenchmarkService(db)
    run = await service.get_run(run_id)
    cases = await service.get_case_results(run.id)
    return {
        "run_id": run.run_id,
        "status": run.status,
        "items": [
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
            }
            for case in cases
        ],
    }


@router.post("/benchmark-runs/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_benchmark_run(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*EDITOR_ROLES)),
) -> dict[str, Any]:
    service = BenchmarkService(db)
    run = await service.get_run(run_id)
    if user.role != "admin" and not run.dry_run:
        raise AuthorizationError("Only administrators may resume live provider benchmarks.")

    await AuditService(db).record(
        action="benchmark.resume",
        outcome="success",
        actor_user_id=user.id,
        target_type="benchmark_run",
        target_id=run.run_id,
        request_id=getattr(request.state, "request_id", None),
        details={"dry_run": run.dry_run, "status_before": run.status},
    )
    if run.status in {"completed", "failed", "cancelled"}:
        await db.commit()
        return {"run_id": run.run_id, "status": run.status, "dry_run": run.dry_run, "resumed": True}

    run = await service.resume_run(run_id)
    return {"run_id": run.run_id, "status": run.status, "dry_run": run.dry_run, "resumed": True}


@router.post("/benchmark-runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_benchmark_run(
    run_id: str,
    request: Request,
    payload: BenchmarkRunCancelRequest | None = None,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_roles(*ADMIN_ROLES)),
) -> dict[str, Any]:
    service = BenchmarkService(db)
    run = await service.get_run(run_id)
    if run.status in {"completed", "failed", "cancelled"}:
        raise ConflictError("Cannot cancel a terminal benchmark run.", details={"run_id": run_id, "status": run.status})

    await AuditService(db).record(
        action="benchmark.cancel",
        outcome="success",
        actor_user_id=actor.id,
        target_type="benchmark_run",
        target_id=run.run_id,
        request_id=getattr(request.state, "request_id", None),
        details={"dry_run": run.dry_run, "status_before": run.status, "reason_provided": bool(payload and payload.reason)},
    )
    run = await service.cancel_run(run_id, reason=(payload.reason if payload else None))
    return {"run_id": run.run_id, "status": run.status, "cancelled": True}


@router.get("/benchmark-runs/{run_id}/export")
async def export_benchmark_run(run_id: str, format: str = Query(default="json", pattern="^(json|csv)$"), db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)) -> Response:
    service = BenchmarkService(db)
    run = await service.get_run(run_id)
    export_data = await service.export_run(run.id, output_format=format)
    if format == "csv":
        return Response(content=export_data, media_type="text/csv; charset=utf-8")
    return Response(content=export_data, media_type="application/json; charset=utf-8")
