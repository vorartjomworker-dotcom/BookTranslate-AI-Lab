from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from ebooklib import epub

from app.document.epub_parser import EpubParser


def _write_epub(path: Path, titles: list[str], paragraphs: list[str]) -> None:
    book = epub.EpubBook()
    book.set_identifier("test-book")
    book.set_title("Test Book")
    book.set_language("en")

    chapters = []
    for index, title in enumerate(titles):
        content = f"<h1>{title}</h1><p>{paragraphs[index]}</p>"
        chapter = epub.EpubHtml(title=title, file_name=f"chapter_{index}.xhtml", content=content)
        book.add_item(chapter)
        chapters.append(chapter)

    book.toc = tuple(chapters)
    book.spine = ['nav', *chapters]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(path, book)


def test_epub_parser_handles_multiple_spine_chapters() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "book.epub"
        _write_epub(path, ["Chapter One", "Chapter Two"], ["First chapter body.", "Second chapter body."])

        document = asyncio.run(EpubParser().parse(path))

        assert len(document.chapters) == 2
        assert document.chapters[0].title == "Chapter One"
        assert "First chapter body." in document.chapters[0].content
        assert document.chapters[1].title == "Chapter Two"


def test_epub_parser_rejects_empty_content() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "empty.epub"
        book = epub.EpubBook()
        book.set_identifier("empty")
        book.set_title("Empty")
        chapter = epub.EpubHtml(title="Empty chapter", file_name="empty.xhtml", content="<p></p>")
        book.add_item(chapter)
        book.spine = ['nav', chapter]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        epub.write_epub(path, book)

        try:
            asyncio.run(EpubParser().parse(path))
            raise AssertionError("Expected ValueError for empty EPUB content")
        except ValueError as exc:
            assert "readable content" in str(exc).lower()
