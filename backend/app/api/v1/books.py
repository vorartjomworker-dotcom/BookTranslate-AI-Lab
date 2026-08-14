from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.core.pagination import MAX_PAGE_SIZE, build_paginated_response, normalize_pagination
from app.dependencies.db import get_db
from app.document.ingestion_service import DocumentIngestionService
from app.models import Book, Chapter
from app.schemas.book import BookCreate, BookRead, BookUpdate
from app.services.book_service import BookService

router = APIRouter(prefix="/api/v1/books", tags=["books"])


@router.get("", response_model=dict[str, Any])
async def list_books(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = BookService(db)
    page, page_size = normalize_pagination(page, page_size)
    items, total = await service.list_books(page=page, page_size=page_size)
    return build_paginated_response([BookRead.model_validate(item).model_dump() for item in items], total, page=page, page_size=page_size)


@router.get("/{book_id}", response_model=BookRead)
async def get_book(book_id: int, db: AsyncSession = Depends(get_db)) -> BookRead:
    service = BookService(db)
    item = await service.get_book(book_id)
    return BookRead.model_validate(item)



@router.post("", response_model=BookRead, status_code=status.HTTP_201_CREATED)
async def create_book(payload: BookCreate, db: AsyncSession = Depends(get_db)) -> BookRead:
    service = BookService(db)
    item = await service.create_book(payload.model_dump())
    return BookRead.model_validate(item)


@router.patch("/{book_id}", response_model=BookRead)
async def patch_book(book_id: int, payload: BookUpdate, db: AsyncSession = Depends(get_db)) -> BookRead:
    service = BookService(db)
    item = await service.update_book(book_id, payload.model_dump(exclude_unset=True))
    return BookRead.model_validate(item)


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_book(book_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    service = BookService(db)
    await service.delete_book(book_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{book_id}/chapters", response_model=dict[str, Any])
async def list_book_chapters(
    book_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = BookService(db)
    page, page_size = normalize_pagination(page, page_size)
    items, total = await service.list_chapters(book_id, page=page, page_size=page_size)
    return build_paginated_response(
        [
            {
                "id": item.id,
                "book_id": item.book_id,
                "chapter_number": item.chapter_number,
                "title": item.title,
                "content": item.content,
                "status": item.status,
            }
            for item in items
        ],
        total,
        page=page,
        page_size=page_size,
    )


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_book_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    author: str | None = Form(default=None),
    language: str | None = Form(default=None),
    description: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if file is None:
        raise ValidationError("A file upload is required.")
    service = DocumentIngestionService(db)
    return await service.ingest_upload(
        upload=file,
        title=title,
        author=author,
        language=language,
        description=description,
    )
