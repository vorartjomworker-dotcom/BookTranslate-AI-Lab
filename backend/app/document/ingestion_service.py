from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, PayloadTooLargeError, UnsupportedMediaTypeError, ValidationError
from app.document.archive_validation import validate_upload_size, validate_zip_archive
from app.document.docx_parser import DocxParser
from app.document.epub_parser import EpubParser
from app.document.segmentation import TextSegmenter
from app.document.storage import DocumentStorage
from app.models import Book, Chapter, Segment


class DocumentIngestionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.storage = DocumentStorage(settings.upload_dir_path)
        self.segmenter = TextSegmenter(settings.segment_target_chars, settings.segment_hard_limit_chars)

    async def ingest_upload(
        self,
        *,
        upload: UploadFile,
        title: str | None,
        author: str | None,
        language: str | None,
        description: str | None,
    ) -> dict[str, Any]:
        if upload.filename is None:
            raise ValidationError("Uploaded file is missing a filename.")

        suffix = Path(upload.filename).suffix.lower()
        if suffix not in {".docx", ".epub"}:
            raise UnsupportedMediaTypeError("Unsupported file type. Only DOCX and EPUB are supported.", details={"format": suffix or "unknown"})

        try:
            safe_name = self.storage.save_upload(upload)
        except ValueError as exc:
            if "Upload exceeds maximum supported size" in str(exc):
                raise PayloadTooLargeError(str(exc)) from exc
            raise ValidationError(str(exc)) from exc

        safe_path = str(self.storage.base_dir / safe_name)

        try:
            if suffix == ".docx":
                await self._validate_docx_file(safe_path)
                parser = DocxParser()
            else:
                await self._validate_epub_file(safe_path)
                parser = EpubParser()

            document = await parser.parse(safe_path)
            if not document.chapters or not any(chapter.content.strip() for chapter in document.chapters):
                raise ValidationError("Document contains no readable content.")

            book_title = title or document.title or Path(upload.filename).stem
            if not book_title.strip():
                book_title = "Uploaded document"

            book = Book(
                title=book_title,
                author=author or document.author,
                description=description or document.description,
                file_path=safe_name,
                file_type=suffix.lstrip("."),
                language=(language or document.language or settings.default_source_language).strip() or settings.default_source_language,
                status="parsed",
            )
            self.session.add(book)
            await self.session.flush()

            chapters: list[Chapter] = []
            segment_total = 0
            for chapter_index, parsed_chapter in enumerate(document.chapters, start=1):
                chapter = Chapter(
                    book_id=book.id,
                    chapter_number=chapter_index,
                    title=(parsed_chapter.title or f"Chapter {chapter_index}").strip() or f"Chapter {chapter_index}",
                    content=parsed_chapter.content,
                    status="segmented",
                )
                self.session.add(chapter)
                await self.session.flush()
                chapters.append(chapter)

                segments = self.segmenter.segment(parsed_chapter.content)
                for segment_index, segment_text in enumerate(segments, start=1):
                    segment = Segment(
                        chapter_id=chapter.id,
                        segment_number=segment_index,
                        original_text=segment_text,
                        translated_text=None,
                        status="pending",
                    )
                    self.session.add(segment)
                segment_total += len(segments)

            await self.session.commit()
            return {
                "book": {
                    "id": book.id,
                    "title": book.title,
                    "author": book.author,
                    "description": book.description,
                    "file_path": book.file_path,
                    "file_type": book.file_type,
                    "language": book.language,
                    "status": book.status,
                },
                "chapters_count": len(chapters),
                "segments_count": segment_total,
            }
        except (IntegrityError, ValueError) as exc:
            await self.session.rollback()
            self.storage.cleanup(safe_name)
            if isinstance(exc, IntegrityError):
                raise ConflictError("Document ingestion conflicts with existing data.") from exc
            if isinstance(exc, ValueError):
                raise ValidationError(str(exc)) from exc
            raise
        except Exception as exc:
            await self.session.rollback()
            self.storage.cleanup(safe_name)
            raise ValidationError("The uploaded document could not be processed.") from exc

    async def _validate_docx_file(self, file_path: str) -> None:
        try:
            validate_zip_archive(file_path)
            from docx import Document
            doc = Document(file_path)
            if not any((p.text or "").strip() for p in doc.paragraphs):
                raise ValueError("Document is empty.")
        except Exception as exc:
            raise ValueError("Document could not be parsed as DOCX.") from exc

    async def _validate_epub_file(self, file_path: str) -> None:
        try:
            validate_zip_archive(file_path)
            from ebooklib import epub
            book = epub.read_epub(file_path)
            if not book.spine:
                raise ValueError("EPUB has no readable spine.")
            spine_text = []
            for item in book.spine:
                item_id = item[0] if isinstance(item, tuple) else item
                if not isinstance(item_id, str):
                    continue
                item_obj = book.get_item_with_id(item_id)
                if item_obj is None or not hasattr(item_obj, "get_content"):
                    continue
                name = getattr(item_obj, "get_name", lambda: "")()
                if isinstance(name, str) and "nav" in name.lower():
                    continue
                content = item_obj.get_content()
                if isinstance(content, bytes):
                    content = content.decode("utf-8", errors="ignore")
                if content is None:
                    continue
                text = str(content)
                if not text.strip():
                    continue
                spine_text.append(text)
            if not any(spine_text):
                raise ValueError("EPUB contains no readable content.")
        except Exception as exc:
            raise ValueError("Document could not be parsed as EPUB.") from exc
