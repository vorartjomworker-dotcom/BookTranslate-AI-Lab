from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditService, audit_hash
from app.auth.rate_limit import enforce_login_rate_limit
from app.core.exceptions import APIError, AuthenticationError
from app.core.security import normalize_email
from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db
from app.models import User
from app.schemas.user import AccessTokenResponse, LoginRequest, UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    client_ip = request.client.host if request.client is not None else "unknown"
    request_id = getattr(request.state, "request_id", None)
    subject_hash = audit_hash("login_subject", normalize_email(payload.email))
    source_hash = audit_hash("login_source", client_ip)
    audit = AuditService(db)

    try:
        await enforce_login_rate_limit(email=payload.email, client_ip=client_ip)
    except APIError as exc:
        outcome = "rate_limited" if exc.http_status == 429 else "service_unavailable"
        await audit.record(
            action="auth.login",
            outcome=outcome,
            subject_hash=subject_hash,
            source_hash=source_hash,
            request_id=request_id,
            details={"http_status": exc.http_status},
        )
        await db.commit()
        raise

    service = AuthService(db)
    try:
        user = await service.authenticate(email=payload.email, password=payload.password)
    except AuthenticationError as exc:
        await audit.record(
            action="auth.login",
            outcome="failure",
            subject_hash=subject_hash,
            source_hash=source_hash,
            request_id=request_id,
            details={"http_status": exc.http_status},
        )
        await db.commit()
        raise

    await audit.record(
        action="auth.login",
        outcome="success",
        actor_user_id=user.id,
        target_type="user",
        target_id=user.id,
        subject_hash=subject_hash,
        source_hash=source_hash,
        request_id=request_id,
    )
    await db.commit()

    access_token, expires_in = await service.issue_tokens(user)
    return AccessTokenResponse(access_token=access_token, expires_in=expires_in, user=UserRead.model_validate(user))


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(user)
