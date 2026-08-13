from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Segment


class SegmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, *, offset: int, limit: int, order_by: Any) -> list[Segment]:
        stmt = select(Segment).offset(offset).limit(limit).order_by(order_by)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.session.execute(select(func.count(Segment.id)))
        return int(result.scalar_one() or 0)

    async def get_by_id(self, segment_id: int) -> Segment | None:
        return await self.session.get(Segment, segment_id)

    async def create(self, payload: dict[str, Any]) -> Segment:
        segment = Segment(**payload)
        self.session.add(segment)
        await self.session.flush()
        await self.session.refresh(segment)
        return segment

    async def update(self, segment: Segment, payload: dict[str, Any]) -> Segment:
        for field, value in payload.items():
            if value is not None:
                setattr(segment, field, value)
        await self.session.flush()
        await self.session.refresh(segment)
        return segment

    async def delete(self, segment: Segment) -> None:
        await self.session.delete(segment)
        await self.session.flush()

    async def get_by_chapter_and_number(self, chapter_id: int, segment_number: int) -> Segment | None:
        stmt = select(Segment).where(Segment.chapter_id == chapter_id, Segment.segment_number == segment_number)
        result = await self.session.execute(stmt)
        return result.scalars().first()
