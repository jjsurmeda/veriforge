from __future__ import annotations

from pathlib import Path

import filetype

from errors import AppError

ALLOWED_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/html",
    "text/csv",
    "text/plain",
    "text/markdown",
}

_EXT_MIMES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html",
    ".htm": "text/html",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


class IngestError(AppError):
    status_code = 422

    def __init__(self, message: str, detail: object = None) -> None:
        super().__init__("ingest_error", message, detail, status_code=422)


def sniff_mime(filename: str, data: bytes) -> str | None:
    kind = filetype.guess(data)
    if kind is not None and kind.mime in ALLOWED_MIMES:
        return str(kind.mime)

    ext = Path(filename).suffix.lower()
    mime = _EXT_MIMES.get(ext)
    if mime is None:
        return None

    if ext == ".pdf":
        return mime if data.startswith(b"%PDF") else None
    if ext in {".docx", ".pptx", ".xlsx"}:
        return mime if data.startswith(b"PK\x03\x04") else None

    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return mime
