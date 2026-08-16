from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.core.security import normalize_email


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_normalized_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.normalized_email == email))
        return result.scalar_one_or_none()

    async def list(self) -> list[User]:
        result = await self.session.execute(select(User).order_by(User.id))
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.session.execute(select(func.count(User.id)))
        return int(result.scalar_one() or 0)

    async def create(self, *, email: str, password_hash: str, role: str) -> User:
        normalized_email = normalize_email(email)
        user = User(email=email, normalized_email=normalized_email, password_hash=password_hash, role=role, is_active=True)
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user
