from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.roles import ADMIN_ROLES, ROLE_ADMIN
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
    repository = UserRepository(db)
    user = await repository.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")

    changes = payload.model_dump(exclude_unset=True)
    # Defense in depth: the schema rejects explicit nulls, but keep the route
    # aligned with the NOT NULL database contract in case validation changes.
    null_fields = [field for field in ("role", "is_active") if field in changes and changes[field] is None]
    if null_fields:
        raise ValidationError(
            "User role and active state must not be null.",
            details={"fields": null_fields},
        )

    removes_active_admin = (
        user.role == ROLE_ADMIN
        and user.is_active
        and (
            ("role" in changes and changes["role"] != ROLE_ADMIN)
            or ("is_active" in changes and changes["is_active"] is False)
        )
    )
    if removes_active_admin:
        active_admins = await repository.lock_active_admins()
        active_admin_ids = {admin.id for admin in active_admins}
        if user.id in active_admin_ids and len(active_admins) == 1:
            raise ConflictError(
                "Cannot deactivate or demote the last active administrator.",
                details={"user_id": user.id},
            )

    for field, value in changes.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user
