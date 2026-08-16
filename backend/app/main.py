from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import APIError, ConflictError, NotFoundError, PayloadTooLargeError, UnsupportedMediaTypeError
from app.db import check_database, close_database
from app.redis_client import check_redis


_SERIALIZER_MANAGED_HEADERS = {"content-length", "content-type"}


def _exception_response_headers(headers: dict[str, str] | None) -> dict[str, str]:
    return {
        name: value
        for name, value in (headers or {}).items()
        if name.lower() not in _SERIALIZER_MANAGED_HEADERS
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        yield
    finally:
        await close_database()


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
    return JSONResponse(
        status_code=exc.http_status,
        content=exc.to_dict(request_id),
        headers=_exception_response_headers(exc.headers),
    )


@app.exception_handler(PayloadTooLargeError)
async def payload_too_large_exception_handler(request: Request, exc: PayloadTooLargeError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    return JSONResponse(status_code=413, content=exc.to_dict(request_id))


@app.exception_handler(UnsupportedMediaTypeError)
async def unsupported_media_type_exception_handler(request: Request, exc: UnsupportedMediaTypeError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    return JSONResponse(status_code=415, content=exc.to_dict(request_id))


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


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": "http_error",
            "message": exc.detail if hasattr(exc, "detail") else exc.__class__.__name__,
            "details": {},
            "request_id": request_id,
        },
        headers=_exception_response_headers(dict(exc.headers or {})),
    )


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=False,
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


_HEALTH_CHECK_TIMEOUT_SECONDS = 2.0


async def _safe_dependency_check(check: Callable[[], Awaitable[bool]]) -> bool:
    """Run a dependency check with a bounded timeout, never raising or hanging."""
    try:
        return await asyncio.wait_for(check(), timeout=_HEALTH_CHECK_TIMEOUT_SECONDS)
    except Exception:
        return False


async def _check_dependencies() -> tuple[bool, bool]:
    return await asyncio.gather(
        _safe_dependency_check(check_database),
        _safe_dependency_check(check_redis),
    )


@app.get("/health")
async def health() -> dict[str, object]:
    """Legacy alias kept for backward compatibility; mirrors liveness-style 200 with a degraded status field.

    Prefer `/health/live` for orchestration liveness probes and `/health/ready` for readiness probes.
    """
    db_ok, redis_ok = await _check_dependencies()
    overall_status = "ok" if (db_ok and redis_ok) else "degraded"

    return {
        "status": overall_status,
        "database": db_ok,
        "redis": redis_ok,
    }


@app.get("/health/live")
async def health_live() -> dict[str, object]:
    """Liveness probe: succeeds whenever the FastAPI process can handle a request, independent of dependencies."""
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready() -> JSONResponse:
    """Readiness probe: 200 only when PostgreSQL schema and Redis are ready, otherwise 503."""
    db_ok, redis_ok = await _check_dependencies()
    ready = db_ok and redis_ok
    payload = {
        "status": "ok" if ready else "degraded",
        "database": db_ok,
        "redis": redis_ok,
    }
    return JSONResponse(status_code=200 if ready else 503, content=payload)
