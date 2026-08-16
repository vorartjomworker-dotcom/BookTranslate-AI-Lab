from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def _expected_alembic_heads() -> frozenset[str]:
    """Return the migration heads shipped with this application build."""
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    heads = frozenset(ScriptDirectory.from_config(config).get_heads())
    if not heads:
        raise RuntimeError("No Alembic migration heads were found.")
    return heads


async def check_database() -> bool:
    """Return True only when PostgreSQL is reachable and its schema is at the shipped Alembic head."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
        result = await connection.execute(text("SELECT version_num FROM alembic_version"))
        current_revisions = frozenset(row[0] for row in result)

    return current_revisions == _expected_alembic_heads()
