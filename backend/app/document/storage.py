from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings


class DocumentStorage:
    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir or settings.upload_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def build_safe_name(self, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".docx", ".epub"}:
            raise ValueError("Unsupported file type.")
        return f"{uuid4().hex}{suffix}"

    def save_upload(self, upload: UploadFile, *, keep_name: bool = False) -> str:
        if upload.filename is None:
            raise ValueError("Uploaded file is missing a filename.")

        safe_name = self.build_safe_name(upload.filename) if not keep_name else os.path.basename(upload.filename)
        target = self.base_dir / safe_name
        temp_path = self.base_dir / f"{uuid4().hex}.part"
        total = 0

        try:
            upload.file.seek(0)
            with temp_path.open("wb") as destination:
                while True:
                    chunk = upload.file.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > settings.max_upload_size_mb * 1024 * 1024:
                        raise ValueError("Upload exceeds maximum supported size.")
                    destination.write(chunk)
            os.replace(temp_path, target)
            return safe_name
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            if target.exists():
                target.unlink(missing_ok=True)
            raise

    def delete_file(self, file_path: str | os.PathLike[str]) -> None:
        target = Path(file_path)
        if not target.is_absolute():
            target = self.base_dir / target
        if target.exists():
            target.unlink(missing_ok=True)

    def cleanup(self, *paths: str | os.PathLike[str]) -> None:
        for path in paths:
            self.delete_file(path)
