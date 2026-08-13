"""Add API persistence constraints for chapter and segment ordering.

Revision ID: 002
Revises: 001
Create Date: 2026-08-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_chapters_book_number",
        "chapters",
        ["book_id", "chapter_number"],
    )
    op.create_unique_constraint(
        "uq_segments_chapter_number",
        "segments",
        ["chapter_id", "segment_number"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_segments_chapter_number", "segments", type_="unique")
    op.drop_constraint("uq_chapters_book_number", "chapters", type_="unique")
