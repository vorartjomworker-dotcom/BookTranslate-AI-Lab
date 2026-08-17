"""Add per-user access token version for immediate revocation.

Revision ID: 009
Revises: 008
Create Date: 2026-08-17 02:35:00.000000

"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_check_constraint(
        "ck_users_token_version_nonnegative",
        "users",
        "token_version >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_token_version_nonnegative", "users", type_="check")
    op.drop_column("users", "token_version")
