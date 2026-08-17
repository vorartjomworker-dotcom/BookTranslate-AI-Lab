from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.dependencies.db import get_db
from app.models import User
from app.services.auth_service import AuthService

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication required.", bearer_challenge=True)
    service = AuthService(db)
    try:
        return await service.get_user_from_access_token(credentials.credentials)
    except AuthenticationError as exc:
        raise AuthenticationError("Invalid or expired token.", bearer_challenge=True) from exc


def require_roles(*allowed_roles: str):
    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise AuthorizationError("You do not have permission to perform this action.")
        return user

    return _dependency


def require_role(role: str):
    return require_roles(role)
