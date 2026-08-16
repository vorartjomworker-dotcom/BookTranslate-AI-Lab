from __future__ import annotations

import asyncio
import getpass
import os
from email_validator import validate_email

from app.core.config import settings
from app.core.roles import ROLE_ADMIN
from app.core.security import hash_password, normalize_email, validate_password_policy
from app.db import async_session_factory
from app.repositories.user_repository import UserRepository


async def bootstrap() -> None:
    email = os.getenv("ADMIN_EMAIL") or input("Admin email: ")
    password = os.getenv("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    normalized_email = normalize_email(validate_email(email).email)
    try:
        validate_password_policy(password)
    except ValueError as exc:
        raise SystemExit(f"Admin bootstrap refused: {exc}") from None

    async with async_session_factory() as session:
        repository = UserRepository(session)
        if await repository.count_active_admins() > 0:
            raise SystemExit("Admin bootstrap refused: an active administrator already exists.")
        if await repository.get_by_normalized_email(normalized_email):
            raise SystemExit(
                "Admin bootstrap refused: that email already belongs to an existing user; use an unused email for recovery."
            )
        await repository.create(email=normalized_email, password_hash=hash_password(password), role=ROLE_ADMIN)
        await session.commit()
    print(f"Created admin user {normalized_email}.")


if __name__ == "__main__":
    asyncio.run(bootstrap())
