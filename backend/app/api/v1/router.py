from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.admin import router as admin_router
from app.api.v1.audit import router as audit_router
from app.api.v1.benchmark_runs import router as benchmark_runs_router
from app.api.v1.books import router as books_router
from app.api.v1.chapters import router as chapters_router
from app.api.v1.quality import router as quality_router
from app.api.v1.segments import router as segments_router
from app.api.v1.translation_jobs import router as translation_jobs_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(audit_router)
api_router.include_router(benchmark_runs_router)
api_router.include_router(books_router)
api_router.include_router(chapters_router)
api_router.include_router(segments_router)
api_router.include_router(translation_jobs_router)
api_router.include_router(quality_router)
