from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chapter, Segment


class ChapterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, *, offset: int, limit: int, order_by: Any) -> list[Chapter]:
        stmt = select(Chapter).offset(offset).limit(limit).order_by(order_by)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.session.execute(select(func.count(Chapter.id)))
        return int(result.scalar_one() or 0)

    async def get_by_id(self, chapter_id: int) -> Chapter | None:
        return await self.session.get(Chapter, chapter_id)

    async def create(self, payload: dict[str, Any]) -> Chapter:
        chapter = Chapter(**payload)
        self.session.add(chapter)
        await self.session.flush()
        await self.session.refresh(chapter)
        return chapter

    async def update(self, chapter: Chapter, payload: dict[str, Any]) -> Chapter:
        for field, value in payload.items():
            if value is not None:
                setattr(chapter, field, value)
        await self.session.flush()
        await self.session.refresh(chapter)
        return chapter

    async def delete(self, chapter: Chapter) -> None:
        await self.session.delete(chapter)
        await self.session.flush()

    async def get_segments(self, chapter_id: int, *, offset: int, limit: int, order_by: Any) -> list[Segment]:
        stmt = (
            select(Segment)
            .where(Segment.chapter_id == chapter_id)
            .offset(offset)
            .limit(limit)
            .order_by(order_by)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_segments(self, chapter_id: int) -> int:
        result = await self.session.execute(select(func.count(Segment.id)).where(Segment.chapter_id == chapter_id))
        return int(result.scalar_one() or 0)

    async def get_by_book_and_number(self, book_id: int, chapter_number: int) -> Chapter | None:
        stmt = select(Chapter).where(Chapter.book_id == book_id, Chapter.chapter_number == chapter_number)
        result = await self.session.execute(stmt)
        return result.scalars().first()
