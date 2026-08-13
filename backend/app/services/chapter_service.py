from __future__ import annotations

from typing import Any

from sqlalchemy import asc
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Book, Chapter, Segment
from app.repositories.chapter_repository import ChapterRepository


class ChapterService:
    def __init__(self, session: Any) -> None:
        self.repository = ChapterRepository(session)
        self.session = session

    async def list_chapters(self, *, page: int, page_size: int) -> tuple[list[Chapter], int]:
        page, page_size = self._normalize_pagination(page, page_size)
        offset = (page - 1) * page_size
        chapters = await self.repository.list(offset=offset, limit=page_size, order_by=asc(Chapter.id))
        total = await self.repository.count()
        return chapters, total

    async def get_chapter(self, chapter_id: int) -> Chapter:
        chapter = await self.repository.get_by_id(chapter_id)
        if chapter is None:
            raise NotFoundError("chapter", chapter_id)
        return chapter

    async def create_chapter_for_book(self, book_id: int, payload: dict[str, Any]) -> Chapter:
        existing = await self.repository.get_by_book_and_number(book_id, payload["chapter_number"])
        if existing is not None:
            raise ConflictError(
                "Chapter number already exists for this book.",
                details={"book_id": book_id, "chapter_number": payload["chapter_number"]},
            )
        chapter = await self.repository.create({**payload, "book_id": book_id})
        try:
            await self.session.commit()
            return chapter
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Chapter creation violates a database constraint.") from exc

    async def update_chapter(self, chapter_id: int, payload: dict[str, Any]) -> Chapter:
        chapter = await self.get_chapter(chapter_id)
        try:
            updated = await self.repository.update(chapter, payload)
            await self.session.commit()
            return updated
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Chapter update violates a database constraint.") from exc

    async def delete_chapter(self, chapter_id: int) -> None:
        chapter = await self.get_chapter(chapter_id)
        try:
            await self.repository.delete(chapter)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Chapter deletion violates a database constraint.") from exc

    async def list_segments(self, chapter_id: int, *, page: int, page_size: int) -> tuple[list[Segment], int]:
        await self.get_chapter(chapter_id)
        page, page_size = self._normalize_pagination(page, page_size)
        offset = (page - 1) * page_size
        segments = await self.repository.get_segments(chapter_id, offset=offset, limit=page_size, order_by=asc(Segment.id))
        total = await self.repository.count_segments(chapter_id)
        return segments, total

    @staticmethod
    def _normalize_pagination(page: int, page_size: int) -> tuple[int, int]:
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 1
        if page_size > 100:
            page_size = 100
        return page, page_size
