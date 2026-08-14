from __future__ import annotations

import io
from pathlib import Path

from fastapi import UploadFile

from app.document.storage import DocumentStorage


def test_save_upload_uses_relative_uuid_name_and_stores_file() -> None:
    storage = DocumentStorage(Path("/tmp/booktranslate-storage"))
    payload = b"This is a DOCX body. " * 10
    upload = UploadFile(filename="sample.docx", file=io.BytesIO(payload))

    stored_key = storage.save_upload(upload)

    assert isinstance(stored_key, str)
    assert not Path(stored_key).is_absolute()
    assert stored_key.endswith(".docx")
    assert (storage.base_dir / stored_key).exists()


def test_storage_rejects_invalid_extension() -> None:
    storage = DocumentStorage(Path("/tmp/booktranslate-storage-invalid"))
    try:
        storage.build_safe_name("notes.txt")
        raise AssertionError("Expected ValueError for invalid suffix")
    except ValueError as exc:
        assert "Unsupported file type" in str(exc)


def test_cleanup_removes_final_file() -> None:
    storage = DocumentStorage(Path("/tmp/booktranslate-storage-cleanup"))
    path = storage.base_dir / "remove-me.docx"
    path.write_bytes(b"test")

    storage.cleanup(path)

    assert not path.exists()
