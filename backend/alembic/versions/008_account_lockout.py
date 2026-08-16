"""Add durable account lockout state.

Revision ID: 008
Revises: 007
Create Date: 2026-08-17 02:00:00.000000

"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_failed_login_attempts_nonnegative",
        "users",
        "failed_login_attempts >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_failed_login_attempts_nonnegative", "users", type_="check")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
