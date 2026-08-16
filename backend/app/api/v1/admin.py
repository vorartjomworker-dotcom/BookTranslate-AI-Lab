from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import IntegrityError
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

# The database uniqueness constraints are the source of truth for duplicate
# detection. The SELECT pre-check in `create_user` is only a UX/performance
# optimization and cannot prevent a TOCTOU race between concurrent requests.
# `email` and `normalized_email` are both unique in migration 006, so either
# index may be the first constraint PostgreSQL reports for a duplicate user.
_DUPLICATE_EMAIL_SQLSTATE = "23505"  # PostgreSQL unique_violation
_DUPLICATE_EMAIL_CONSTRAINTS = frozenset({"ix_users_email", "ix_users_normalized_email"})


def _is_duplicate_user_email_integrity_error(exc: IntegrityError) -> bool:
    """Return True only for PostgreSQL uniqueness violations on user email indexes.

    SQLAlchemy's asyncpg adapter can expose SQLSTATE on its translated DBAPI
    exception while asyncpg's original exception (available through the cause
    chain) carries the structured constraint name. Walk that exception chain so
    classification remains structural and does not depend on parsing error text.
    """

    current: object | None = exc.orig
    seen: set[int] = set()
    sqlstate: str | None = None
    constraint_name: str | None = None

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        sqlstate = sqlstate or getattr(current, "sqlstate", None)
        constraint_name = constraint_name or getattr(current, "constraint_name", None)
        if sqlstate is not None and constraint_name is not None:
            break
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)

    return sqlstate == _DUPLICATE_EMAIL_SQLSTATE and constraint_name in _DUPLICATE_EMAIL_CONSTRAINTS


@router.get("", response_model=list[UserRead])
async def list_users(db: AsyncSession = Depends(get_db), _: User = Depends(require_roles(*ADMIN_ROLES))) -> list[User]:
    return await UserRepository(db).list()


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db), _: User = Depends(require_roles(*ADMIN_ROLES))) -> User:
    repository = UserRepository(db)
    normalized_email = normalize_email(payload.email)
    if await repository.get_by_normalized_email(normalized_email):
        raise ConflictError("A user with this email already exists.")
    try:
        user = await repository.create(email=payload.email, password_hash=hash_password(payload.password), role=payload.role)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _is_duplicate_user_email_integrity_error(exc):
            raise ConflictError("A user with this email already exists.") from exc
        raise
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
