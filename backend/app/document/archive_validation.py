from __future__ import annotations

import os
import stat
import zipfile
from pathlib import PurePosixPath, PureWindowsPath
from pathlib import Path

from app.core.config import settings


def _is_unsafe_archive_name(name: str) -> bool:
    candidate = name.replace("\\", "/")
    if not candidate:
        return True
    if candidate.startswith("/") or candidate.startswith("\\"):
        return True
    if candidate.startswith("../") or candidate == ".." or candidate.startswith("./"):
        return True
    if PurePosixPath(candidate).parts and any(part in {".", ".."} for part in PurePosixPath(candidate).parts):
        return True
    if PureWindowsPath(candidate).drive:
        return True
    if len(candidate) >= 2 and candidate[1] == ":":
        return True
    return False


def validate_upload_size(size_bytes: int) -> None:
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if size_bytes <= 0:
        raise ValueError("Uploaded file is empty.")
    if size_bytes > max_bytes:
        raise ValueError("Upload exceeds maximum supported size.")


def validate_zip_archive(file_path: str | os.PathLike[str]) -> None:
    path = Path(file_path)
    if not path.exists():
        raise ValueError("Uploaded archive is missing.")

    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if not names:
                raise ValueError("Archive is empty.")

            if len(names) > settings.max_archive_entries:
                raise ValueError("Archive contains too many entries.")

            total_size = 0
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if _is_unsafe_archive_name(info.filename):
                    raise ValueError("Archive contains invalid paths.")

                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise ValueError("Archive contains symbolic links.")
                if info.flag_bits & 0x1:
                    raise ValueError("Archive contains encrypted entries.")

                total_size += info.file_size
                if total_size > settings.max_archive_uncompressed_mb * 1024 * 1024:
                    raise ValueError("Archive exceeds uncompressed size limit.")

                if info.file_size > 0 and info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > settings.max_archive_compression_ratio:
                        raise ValueError("Archive compression ratio exceeds the configured limit.")

            bad_names = [name for name in names if _is_unsafe_archive_name(name)]
            if bad_names:
                raise ValueError("Archive contains unsafe paths.")
    except zipfile.BadZipFile as exc:
        raise ValueError("Uploaded file is not a valid zip archive.") from exc
