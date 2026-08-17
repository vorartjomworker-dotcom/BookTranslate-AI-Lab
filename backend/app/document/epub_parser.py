from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub

from app.document.parser import DocumentParser
from app.document.types import ParsedChapter, ParsedDocument


class EpubParser(DocumentParser):
    def _parse_sync(self, file_path: str | Path) -> ParsedDocument:
        book = epub.read_epub(str(file_path), options={"ignore_ncx": True})

        title = book.get_metadata("DC", "title")
        author = book.get_metadata("DC", "creator")
        raw_title = title[0][0] if title else "Document"
        raw_author = author[0][0] if author else None

        chapters: list[ParsedChapter] = []
        seen_titles: set[str] = set()

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

            doc = item_obj.get_content()
            if doc is None:
                continue
            if isinstance(doc, bytes):
                doc = doc.decode("utf-8", errors="ignore")

            soup = BeautifulSoup(doc, "html.parser")
            for tag in soup(["nav", "style", "script"]):
                tag.decompose()
            text = self._clean_text(soup.get_text("\n", strip=True))
            if not text:
                continue

            heading = self._heading_from_soup(soup)
            key = heading or "untitled"
            if not heading and any(part.lower() in text.lower() for part in ["contents", "table of contents"]):
                continue
            if key in seen_titles:
                existing = next((chapter for chapter in chapters if chapter.title == key), None)
                if existing is not None:
                    existing.content = f"{existing.content}\n\n{text}".strip()
                    continue
            seen_titles.add(key)
            chapters.append(ParsedChapter(title=heading or key, content=text))

        if not chapters:
            raise ValueError("Document contains no readable content.")

        return ParsedDocument(title=raw_title, author=raw_author, chapters=chapters, metadata={"source": "epub"})

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @staticmethod
    def _heading_from_soup(soup: BeautifulSoup) -> str:
        for selector in ("h1", "h2", "title"):
            tag = soup.select_one(selector)
            if tag and tag.get_text(strip=True):
                return tag.get_text(" ", strip=True)
        return ""
