from datetime import datetime

from sqlalchemy import String, Text, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unknown")
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True, server_default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    chapters: Mapped[list["Chapter"]] = relationship(back_populates="book", cascade="all, delete-orphan")
