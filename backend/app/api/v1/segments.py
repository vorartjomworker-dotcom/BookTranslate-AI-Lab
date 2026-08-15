from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.pagination import MAX_PAGE_SIZE, build_paginated_response, normalize_pagination
from app.dependencies.db import get_db
from app.schemas.segment import SegmentCreate, SegmentRead, SegmentUpdate
from app.services.chapter_service import ChapterService
from app.services.segment_service import SegmentService

router = APIRouter(prefix="/api/v1", tags=["segments"])


@router.get("/segments", response_model=dict[str, Any])
async def list_segments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = SegmentService(db)
    page, page_size = normalize_pagination(page, page_size)
    items, total = await service.list_segments(page=page, page_size=page_size)
    return build_paginated_response([SegmentRead.model_validate(item).model_dump() for item in items], total, page=page, page_size=page_size)


@router.get("/segments/{segment_id}", response_model=SegmentRead)
async def get_segment(segment_id: int, db: AsyncSession = Depends(get_db)) -> SegmentRead:
    service = SegmentService(db)
    item = await service.get_segment(segment_id)
    return SegmentRead.model_validate(item)


@router.post("/chapters/{chapter_id}/segments", response_model=SegmentRead, status_code=status.HTTP_201_CREATED)
async def create_chapter_segment(
    chapter_id: int,
    payload: SegmentCreate,
    db: AsyncSession = Depends(get_db),
) -> SegmentRead:
    service = SegmentService(db)
    item = await service.create_segment_for_chapter(chapter_id, payload.model_dump())
    return SegmentRead.model_validate(item)


@router.patch("/segments/{segment_id}", response_model=SegmentRead)
async def patch_segment(segment_id: int, payload: SegmentUpdate, db: AsyncSession = Depends(get_db)) -> SegmentRead:
    service = SegmentService(db)
    item = await service.update_segment(segment_id, payload.model_dump(exclude_unset=True))
    return SegmentRead.model_validate(item)


@router.delete("/segments/{segment_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_segment(segment_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    service = SegmentService(db)
    await service.delete_segment(segment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/chapters/{chapter_id}/segments", response_model=dict[str, Any])
async def list_segments_for_chapter(
    chapter_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = ChapterService(db)
    page, page_size = normalize_pagination(page, page_size)
    items, total = await service.list_segments(chapter_id, page=page, page_size=page_size)
    return build_paginated_response([SegmentRead.model_validate(item).model_dump() for item in items], total, page=page, page_size=page_size)
