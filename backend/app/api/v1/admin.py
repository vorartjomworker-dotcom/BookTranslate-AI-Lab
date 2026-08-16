from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.roles import ADMIN_ROLES
from app.core.security import hash_password, normalize_email
from app.dependencies.auth import require_roles
from app.dependencies.db import get_db
from app.models import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin"])


@router.get("", response_model=list[UserRead])
async def list_users(db: AsyncSession = Depends(get_db), _: User = Depends(require_roles(*ADMIN_ROLES))) -> list[User]:
    return await UserRepository(db).list()


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db), _: User = Depends(require_roles(*ADMIN_ROLES))) -> User:
    repository = UserRepository(db)
    normalized_email = normalize_email(payload.email)
    if await repository.get_by_normalized_email(normalized_email):
        raise ConflictError("A user with this email already exists.")
    user = await repository.create(email=payload.email, password_hash=hash_password(payload.password), role=payload.role)
    await db.commit()
    return user


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(user_id: int, payload: UserUpdate, db: AsyncSession = Depends(get_db), _: User = Depends(require_roles(*ADMIN_ROLES))) -> User:
    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user