from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rate_limit import enforce_login_rate_limit
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
    await enforce_login_rate_limit(email=payload.email, client_ip=client_ip)

    service = AuthService(db)
    user = await service.authenticate(email=payload.email, password=payload.password)
    access_token, expires_in = await service.issue_tokens(user)
    return AccessTokenResponse(access_token=access_token, expires_in=expires_in, user=UserRead.model_validate(user))


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(user)
