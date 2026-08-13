"""Initial migration: create books, chapters, segments tables.

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create books table
    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("file_type", sa.String(length=10), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="uploaded"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_books_title"), "books", ["title"], unique=False)
    op.create_index(op.f("ix_books_status"), "books", ["status"], unique=False)

    # Create chapters table
    op.create_table(
        "chapters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chapters_book_id"), "chapters", ["book_id"], unique=False)
    op.create_index(op.f("ix_chapters_title"), "chapters", ["title"], unique=False)
    op.create_index(op.f("ix_chapters_status"), "chapters", ["status"], unique=False)

    # Create segments table
    op.create_table(
        "segments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("segment_number", sa.Integer(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("model_used", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("qa_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qa_status", sa.String(length=50), nullable=True),
        sa.Column("qa_comment", sa.Text(), nullable=True),
        sa.Column("translation_profile", sa.String(length=50), nullable=False, server_default="general"),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_segments_chapter_id"), "segments", ["chapter_id"], unique=False)
    op.create_index(op.f("ix_segments_status"), "segments", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_segments_status"), table_name="segments")
    op.drop_index(op.f("ix_segments_chapter_id"), table_name="segments")
    op.drop_table("segments")

    op.drop_index(op.f("ix_chapters_status"), table_name="chapters")
    op.drop_index(op.f("ix_chapters_title"), table_name="chapters")
    op.drop_index(op.f("ix_chapters_book_id"), table_name="chapters")
    op.drop_table("chapters")

    op.drop_index(op.f("ix_books_status"), table_name="books")
    op.drop_index(op.f("ix_books_title"), table_name="books")
    op.drop_table("books")
