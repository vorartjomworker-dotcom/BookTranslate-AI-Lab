from __future__ import annotations

from typing import Any

from sqlalchemy import asc
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Segment
from app.repositories.segment_repository import SegmentRepository


class SegmentService:
    def __init__(self, session: Any) -> None:
        self.repository = SegmentRepository(session)
        self.session = session

    async def list_segments(self, *, page: int, page_size: int) -> tuple[list[Segment], int]:
        page, page_size = self._normalize_pagination(page, page_size)
        offset = (page - 1) * page_size
        segments = await self.repository.list(offset=offset, limit=page_size, order_by=asc(Segment.id))
        total = await self.repository.count()
        return segments, total

    async def get_segment(self, segment_id: int) -> Segment:
        segment = await self.repository.get_by_id(segment_id)
        if segment is None:
            raise NotFoundError("segment", segment_id)
        return segment

    async def create_segment_for_chapter(self, chapter_id: int, payload: dict[str, Any]) -> Segment:
        existing = await self.repository.get_by_chapter_and_number(chapter_id, payload["segment_number"])
        if existing is not None:
            raise ConflictError(
                "Segment number already exists for this chapter.",
                details={"chapter_id": chapter_id, "segment_number": payload["segment_number"]},
            )
        segment = await self.repository.create({**payload, "chapter_id": chapter_id})
        try:
            await self.session.commit()
            return segment
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Segment creation violates a database constraint.") from exc

    async def update_segment(self, segment_id: int, payload: dict[str, Any]) -> Segment:
        segment = await self.get_segment(segment_id)
        try:
            updated = await self.repository.update(segment, payload)
            await self.session.commit()
            return updated
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Segment update violates a database constraint.") from exc

    async def delete_segment(self, segment_id: int) -> None:
        segment = await self.get_segment(segment_id)
        try:
            await self.repository.delete(segment)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Segment deletion violates a database constraint.") from exc

    @staticmethod
    def _normalize_pagination(page: int, page_size: int) -> tuple[int, int]:
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 1
        if page_size > 100:
            page_size = 100
        return page, page_size
