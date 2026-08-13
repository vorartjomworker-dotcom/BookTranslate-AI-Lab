from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, Chapter


class BookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, *, offset: int, limit: int, order_by: Any) -> list[Book]:
        stmt = select(Book).offset(offset).limit(limit).order_by(order_by)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.session.execute(select(func.count(Book.id)))
        return int(result.scalar_one() or 0)

    async def get_by_id(self, book_id: int) -> Book | None:
        return await self.session.get(Book, book_id)

    async def create(self, payload: dict[str, Any]) -> Book:
        book = Book(**payload)
        self.session.add(book)
        await self.session.flush()
        await self.session.refresh(book)
        return book

    async def update(self, book: Book, payload: dict[str, Any]) -> Book:
        for field, value in payload.items():
            if value is not None:
                setattr(book, field, value)
        await self.session.flush()
        await self.session.refresh(book)
        return book

    async def delete(self, book: Book) -> None:
        await self.session.delete(book)
        await self.session.flush()

    async def get_chapters(self, book_id: int, *, offset: int, limit: int, order_by: Any) -> list[Chapter]:
        stmt = (
            select(Chapter)
            .where(Chapter.book_id == book_id)
            .offset(offset)
            .limit(limit)
            .order_by(order_by)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_chapters(self, book_id: int) -> int:
        result = await self.session.execute(select(func.count(Chapter.id)).where(Chapter.book_id == book_id))
        return int(result.scalar_one() or 0)
