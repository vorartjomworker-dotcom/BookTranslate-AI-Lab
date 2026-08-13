from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db import check_database, create_tables

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="AI-powered platform for technical book translation",
)


@app.on_event("startup")
async def startup_event():
    await create_tables()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "status": "running",
        "version": "0.1.0",
    }


@app.get("/health")
async def health() -> dict[str, object]:
    try:
        db_ok = await check_database()
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "redis": True,
    }
