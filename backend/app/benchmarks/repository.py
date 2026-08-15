from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BenchmarkCaseResult, BenchmarkRun


class BenchmarkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_run_by_id(self, run_id: str) -> BenchmarkRun | None:
        stmt = select(BenchmarkRun).where(BenchmarkRun.run_id == run_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_run_by_db_id(self, run_id: int) -> BenchmarkRun | None:
        return await self.session.get(BenchmarkRun, run_id)

    async def list_runs(self, *, offset: int, limit: int) -> tuple[list[BenchmarkRun], int]:
        total_stmt = select(func.count(BenchmarkRun.id))
        total_result = await self.session.execute(total_stmt)
        total = int(total_result.scalar_one() or 0)
        stmt = select(BenchmarkRun).order_by(BenchmarkRun.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create_run(self, run: BenchmarkRun) -> BenchmarkRun:
        self.session.add(run)
        await self.session.flush()
        return run

    async def save_run(self, run: BenchmarkRun) -> BenchmarkRun:
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_case_results(self, run_id: int) -> list[BenchmarkCaseResult]:
        stmt = select(BenchmarkCaseResult).where(BenchmarkCaseResult.run_id == run_id).order_by(BenchmarkCaseResult.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert_case_result(self, result: BenchmarkCaseResult) -> BenchmarkCaseResult:
        if result.id is None:
            self.session.add(result)
        await self.session.flush()
        return result

    async def save_case_result(self, result: BenchmarkCaseResult) -> BenchmarkCaseResult:
        return await self.upsert_case_result(result)

    async def get_case_result(self, run_id: int, case_id: str) -> BenchmarkCaseResult | None:
        stmt = select(BenchmarkCaseResult).where(BenchmarkCaseResult.run_id == run_id, BenchmarkCaseResult.case_id == case_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
