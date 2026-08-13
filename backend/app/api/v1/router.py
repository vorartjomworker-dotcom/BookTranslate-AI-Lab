from fastapi import APIRouter

from app.api.v1.books import router as books_router
from app.api.v1.chapters import router as chapters_router
from app.api.v1.segments import router as segments_router

api_router = APIRouter()
api_router.include_router(books_router)
api_router.include_router(chapters_router)
api_router.include_router(segments_router)
