from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db
from app.models import User
from app.schemas.user import AccessTokenResponse, BootstrapAdminRequest, LoginRequest, UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_REFRESH_COOKIE_NAME = "refresh_token"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=settings.auth_refresh_token_expires_days * 24 * 60 * 60,
        path="/api/v1/auth",
    )


@router.post("/bootstrap-admin", response_model=AccessTokenResponse, status_code=status.HTTP_201_CREATED)
async def bootstrap_admin(
    payload: BootstrapAdminRequest,
    response: Response,
    x_bootstrap_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    service = AuthService(db)
    user = await service.bootstrap_admin(email=payload.email, password=payload.password, bootstrap_token=x_bootstrap_token)
    access_token, refresh_token, expires_in = await service.issue_tokens(user)
    _set_refresh_cookie(response, refresh_token)
    return AccessTokenResponse(access_token=access_token, expires_in=expires_in, user=UserRead.model_validate(user))


@router.post("/login", response_model=AccessTokenResponse)
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)) -> AccessTokenResponse:
    service = AuthService(db)
    user = await service.authenticate(email=payload.email, password=payload.password)
    access_token, refresh_token, expires_in = await service.issue_tokens(user)
    _set_refresh_cookie(response, refresh_token)
    return AccessTokenResponse(access_token=access_token, expires_in=expires_in, user=UserRead.model_validate(user))


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> AccessTokenResponse:
    refresh_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise AuthenticationError("Missing refresh token.")
    service = AuthService(db)
    access_token, new_refresh_token, expires_in = await service.refresh_access_token(refresh_token)
    _set_refresh_cookie(response, new_refresh_token)
    payload = await service.get_user_from_access_token(access_token)
    return AccessTokenResponse(access_token=access_token, expires_in=expires_in, user=UserRead.model_validate(payload))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(response: Response, _: User = Depends(get_current_user)) -> Response:
    response.delete_cookie(key=_REFRESH_COOKIE_NAME, path="/api/v1/auth")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(user)
