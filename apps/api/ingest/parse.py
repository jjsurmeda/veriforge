from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from typing import cast

import pdfplumber
from markitdown import MarkItDown

from ingest.accept import IngestError

PDF_MIME = "application/pdf"


@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    page_texts: list[str]


async def parse_document(mime: str, data: bytes) -> ParsedDocument:
    try:
        markdown = await asyncio.to_thread(_markitdown_text, data)
    except Exception as exc:
        if mime != PDF_MIME:
            raise IngestError("Could not parse document") from exc
        markdown = await asyncio.to_thread(_pdf_text, data)

    page_texts = await asyncio.to_thread(_pdf_page_texts, data) if mime == PDF_MIME else []
    return ParsedDocument(markdown=markdown, page_texts=page_texts)


def _markitdown_text(data: bytes) -> str:
    result = MarkItDown().convert(io.BytesIO(data))
    return cast(str, getattr(result, "text_content", ""))


def _pdf_page_texts(data: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def _pdf_text(data: bytes) -> str:
    return "\n\n".join(_pdf_page_texts(data))
