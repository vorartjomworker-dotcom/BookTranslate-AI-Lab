"""Document ingestion primitives for DOCX/EPUB parsing and segmentation."""

from app.document.parser import DocumentParser
from app.document.storage import DocumentStorage
from app.document.segmentation import TextSegmenter
from app.document.types import ParsedChapter, ParsedDocument

__all__ = [
    "DocumentParser",
    "ParsedChapter",
    "ParsedDocument",
    "DocumentStorage",
    "TextSegmenter",
]
