from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import APIError, ConflictError, NotFoundError
from app.db import check_database
from app.redis_client import check_redis


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="AI-powered platform for technical book translation",
    lifespan=lifespan,
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = uuid4().hex
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    except Exception as exc:
        if isinstance(exc, RequestValidationError):
            handler = app.exception_handlers.get(RequestValidationError)
            if handler is not None:
                response = await handler(request, exc)
            else:
                response = JSONResponse(status_code=422, content={"code": "validation_error", "message": "Validation error.", "details": {}, "request_id": request_id})
        elif isinstance(exc, NotFoundError):
            handler = app.exception_handlers.get(NotFoundError)
            if handler is not None:
                response = await handler(request, exc)
            else:
                response = JSONResponse(status_code=404, content=exc.to_dict(request_id))
        elif isinstance(exc, ConflictError):
            handler = app.exception_handlers.get(ConflictError)
            if handler is not None:
                response = await handler(request, exc)
            else:
                response = JSONResponse(status_code=409, content=exc.to_dict(request_id))
        else:
            response = JSONResponse(
                status_code=500,
                content={
                    "code": "internal_server_error",
                    "message": "Internal server error.",
                    "details": {},
                    "request_id": request_id,
                },
            )
        response.headers["X-Request-ID"] = request_id
        return response
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(NotFoundError)
async def not_found_exception_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    return JSONResponse(status_code=404, content=exc.to_dict(request_id))


@app.exception_handler(ConflictError)
async def conflict_exception_handler(request: Request, exc: ConflictError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    return JSONResponse(status_code=409, content=exc.to_dict(request_id))


@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict(request_id))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "message": "Validation error.",
            "details": {"errors": exc.errors()},
            "request_id": request_id,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_server_error",
            "message": "Internal server error.",
            "details": {},
            "request_id": request_id,
        },
    )


app.include_router(api_router)

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

    try:
        redis_ok = await check_redis()
    except Exception:
        redis_ok = False

    overall_status = "ok" if (db_ok and redis_ok) else "degraded"

    return {
        "status": overall_status,
        "database": db_ok,
        "redis": redis_ok,
    }
