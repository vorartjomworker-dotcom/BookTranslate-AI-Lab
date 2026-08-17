from __future__ import annotations

import pytest

import app.db as db_module


class _Result:
    def __init__(self, revisions: list[str]) -> None:
        self._rows = [(revision,) for revision in revisions]

    def __iter__(self):
        return iter(self._rows)


class _Connection:
    def __init__(self, revisions: list[str]) -> None:
        self._revisions = revisions

    async def execute(self, statement):
        sql = str(statement)
        if "alembic_version" in sql:
            return _Result(self._revisions)
        return _Result([])


class _ConnectionContext:
    def __init__(self, revisions: list[str]) -> None:
        self._connection = _Connection(revisions)

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Engine:
    def __init__(self, revisions: list[str]) -> None:
        self._revisions = revisions

    def connect(self):
        return _ConnectionContext(self._revisions)


@pytest.mark.asyncio
async def test_database_readiness_accepts_current_alembic_head(monkeypatch):
    monkeypatch.setattr(db_module, "engine", _Engine(["006"]))
    monkeypatch.setattr(db_module, "_expected_alembic_heads", lambda: frozenset({"006"}))

    assert await db_module.check_database() is True


@pytest.mark.asyncio
async def test_database_readiness_rejects_stale_alembic_revision(monkeypatch):
    monkeypatch.setattr(db_module, "engine", _Engine(["005"]))
    monkeypatch.setattr(db_module, "_expected_alembic_heads", lambda: frozenset({"006"}))

    assert await db_module.check_database() is False


@pytest.mark.asyncio
async def test_database_readiness_requires_all_migration_heads(monkeypatch):
    monkeypatch.setattr(db_module, "engine", _Engine(["006a"]))
    monkeypatch.setattr(db_module, "_expected_alembic_heads", lambda: frozenset({"006a", "006b"}))

    assert await db_module.check_database() is False
