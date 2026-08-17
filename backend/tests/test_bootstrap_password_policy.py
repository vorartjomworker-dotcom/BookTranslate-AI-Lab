from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.auth import bootstrap_admin
from app.repositories.user_repository import UserRepository


async def _user_count(async_session_factory) -> int:
    async with async_session_factory() as session:
        return await UserRepository(session).count()


def _stub_valid_email(monkeypatch) -> None:
    monkeypatch.setattr(
        bootstrap_admin,
        "validate_email",
        lambda email: SimpleNamespace(email=email),
    )


def test_bootstrap_rejects_empty_password_before_database_write(async_session_factory, monkeypatch) -> None:
    monkeypatch.setattr(bootstrap_admin, "async_session_factory", async_session_factory)
    _stub_valid_email(monkeypatch)
    monkeypatch.setenv("ADMIN_EMAIL", "empty-password-admin@example.com")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(bootstrap_admin.getpass, "getpass", lambda prompt: "")

    with pytest.raises(SystemExit, match="at least 8 characters"):
        asyncio.run(bootstrap_admin.bootstrap())

    assert asyncio.run(_user_count(async_session_factory)) == 0


def test_bootstrap_rejects_short_password_before_database_write(async_session_factory, monkeypatch) -> None:
    monkeypatch.setattr(bootstrap_admin, "async_session_factory", async_session_factory)
    _stub_valid_email(monkeypatch)
    monkeypatch.setenv("ADMIN_EMAIL", "short-password-admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "1234567")

    with pytest.raises(SystemExit, match="at least 8 characters"):
        asyncio.run(bootstrap_admin.bootstrap())

    assert asyncio.run(_user_count(async_session_factory)) == 0
