from __future__ import annotations

from typing import Any

from sqlalchemy import asc
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Book, Chapter
from app.repositories.book_repository import BookRepository


class BookService:
    def __init__(self, session: Any) -> None:
        self.repository = BookRepository(session)
        self.session = session

    async def list_books(self, *, page: int, page_size: int) -> tuple[list[Book], int]:
        page, page_size = self._normalize_pagination(page, page_size)
        offset = (page - 1) * page_size
        books = await self.repository.list(offset=offset, limit=page_size, order_by=asc(Book.id))
        total = await self.repository.count()
        return books, total

    async def get_book(self, book_id: int) -> Book:
        book = await self.repository.get_by_id(book_id)
        if book is None:
            raise NotFoundError("book", book_id)
        return book

    async def create_book(self, payload: dict[str, Any]) -> Book:
        try:
            book = await self.repository.create(payload)
            await self.session.commit()
            return book
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Book creation violates a database constraint.") from exc

    async def update_book(self, book_id: int, payload: dict[str, Any]) -> Book:
        book = await self.get_book(book_id)
        try:
            updated = await self.repository.update(book, payload)
            await self.session.commit()
            return updated
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Book update violates a database constraint.") from exc

    async def delete_book(self, book_id: int, *, commit: bool = True) -> None:
        book = await self.get_book(book_id)
        try:
            await self.repository.delete(book)
            if commit:
                await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Book deletion violates a database constraint.") from exc

    async def list_chapters(self, book_id: int, *, page: int, page_size: int) -> tuple[list[Chapter], int]:
        await self.get_book(book_id)
        page, page_size = self._normalize_pagination(page, page_size)
        offset = (page - 1) * page_size
        chapters = await self.repository.get_chapters(book_id, offset=offset, limit=page_size, order_by=asc(Chapter.id))
        total = await self.repository.count_chapters(book_id)
        return chapters, total

    @staticmethod
    def _normalize_pagination(page: int, page_size: int) -> tuple[int, int]:
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 1
        if page_size > 100:
            page_size = 100
        return page, page_size
