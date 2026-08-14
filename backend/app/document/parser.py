from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

from app.document.types import ParsedDocument


class DocumentParser(ABC):
    @abstractmethod
    def _parse_sync(self, file_path: str | Path) -> ParsedDocument:
        raise NotImplementedError

    async def parse(self, file_path: str | Path) -> ParsedDocument:
        return await asyncio.to_thread(self._parse_sync, file_path)
