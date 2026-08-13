from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.pagination import MAX_PAGE_SIZE, build_paginated_response, normalize_pagination
from app.dependencies.db import get_db
from app.schemas.chapter import ChapterCreate, ChapterRead, ChapterUpdate
from app.services.chapter_service import ChapterService

router = APIRouter(prefix="/api/v1", tags=["chapters"])


@router.get("/chapters", response_model=dict[str, Any])
async def list_chapters(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = ChapterService(db)
    page, page_size = normalize_pagination(page, page_size)
    items, total = await service.list_chapters(page=page, page_size=page_size)
    return build_paginated_response([ChapterRead.model_validate(item).model_dump() for item in items], total, page=page, page_size=page_size)


@router.get("/chapters/{chapter_id}", response_model=ChapterRead)
async def get_chapter(chapter_id: int, db: AsyncSession = Depends(get_db)) -> ChapterRead:
    service = ChapterService(db)
    item = await service.get_chapter(chapter_id)
    return ChapterRead.model_validate(item)


@router.post("/books/{book_id}/chapters", response_model=ChapterRead, status_code=status.HTTP_201_CREATED)
async def create_book_chapter(
    book_id: int,
    payload: ChapterCreate,
    db: AsyncSession = Depends(get_db),
) -> ChapterRead:
    service = ChapterService(db)
    item = await service.create_chapter_for_book(book_id, payload.model_dump())
    return ChapterRead.model_validate(item)


@router.patch("/chapters/{chapter_id}", response_model=ChapterRead)
async def patch_chapter(chapter_id: int, payload: ChapterUpdate, db: AsyncSession = Depends(get_db)) -> ChapterRead:
    service = ChapterService(db)
    item = await service.update_chapter(chapter_id, payload.model_dump(exclude_unset=True))
    return ChapterRead.model_validate(item)


@router.delete("/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_chapter(chapter_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    service = ChapterService(db)
    await service.delete_chapter(chapter_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/books/{book_id}/chapters", response_model=dict[str, Any])
async def list_chapters_for_book(
    book_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = BookService(db)
    page, page_size = normalize_pagination(page, page_size)
    items, total = await service.list_chapters(book_id, page=page, page_size=page_size)
    return build_paginated_response([ChapterRead.model_validate(item).model_dump() for item in items], total, page=page, page_size=page_size)


from app.services.book_service import BookService
from app.core.pagination import normalize_pagination
