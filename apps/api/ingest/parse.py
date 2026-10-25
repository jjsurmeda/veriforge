from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from typing import Any, cast

import pdfplumber
from markitdown import MarkItDown
from PIL import Image

from config import get_settings
from ingest.accept import IngestError
from ingest.flags import LOW_TEXT_MIN_CHARS
from ingest.ocr import OcrEngine, OcrError, OcrPage, OcrUnavailable, check_languages, ocr_gate

logger = logging.getLogger(__name__)

PDF_MIME = "application/pdf"
IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
# A page is OCR'd when embedded images cover more than half of it, even with a
# text layer: a full-page scan covers about 100%, a figure with a caption stays
# well under 50%. Below the threshold the text layer is trusted.
IMAGE_COVERAGE_THRESHOLD = 0.5
OCR_LOW_CONFIDENCE = 60


@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    page_texts: list[str]
    ocr_pages: tuple[int, ...] = ()
    ocr_low_confidence_pages: tuple[int, ...] = ()
    ocr_skipped_pages: tuple[int, ...] = ()


async def parse_document(
    mime: str, data: bytes, *, engine: OcrEngine | None = None
) -> ParsedDocument:
    """`engine=None` means OCR is off: scanned pages are skipped and noted."""
    if mime in IMAGE_MIMES:
        return await _parse_image(data, engine)
    try:
        markdown = await asyncio.to_thread(_markitdown_text, data)
    except Exception as exc:
        if mime != PDF_MIME:
            raise IngestError("Could not parse document") from exc
        markdown = await asyncio.to_thread(_pdf_text, data)

    if mime != PDF_MIME:
        return ParsedDocument(markdown=markdown, page_texts=[])
    page_texts = await asyncio.to_thread(_pdf_page_texts, data)
    coverage = await asyncio.to_thread(_image_coverage, data)
    candidates = [
        index
        for index, text in enumerate(page_texts)
        if len(text.strip()) < LOW_TEXT_MIN_CHARS
        or (index < len(coverage) and coverage[index] > IMAGE_COVERAGE_THRESHOLD)
    ]
    if not candidates:
        return ParsedDocument(markdown=markdown, page_texts=page_texts)
    return await _ocr_pages(data, markdown, page_texts, candidates, engine)


async def _ocr_pages(
    data: bytes,
    markdown: str,
    page_texts: list[str],
    candidates: list[int],
    engine: OcrEngine | None,
) -> ParsedDocument:
    settings = get_settings()
    used: list[int] = []
    low: list[int] = []
    skipped: list[int] = []
    texts = list(page_texts)
    todo = candidates[: settings.ocr_max_pages_per_document] if engine else []
    skipped.extend(index + 1 for index in candidates if index not in todo)
    if todo:
        languages = check_languages(settings.ocr_languages)
        pdf = await asyncio.to_thread(pdfplumber.open, io.BytesIO(data))
        try:
            for position, index in enumerate(todo):
                try:
                    image = await asyncio.to_thread(_render, pdf, index, settings.ocr_dpi)
                    async with ocr_gate():
                        assert engine is not None  # todo is empty without an engine
                        result = await engine.recognize(image, languages=languages)
                except OcrUnavailable:
                    skipped.extend(i + 1 for i in todo[position:])
                    break
                except OcrError as exc:
                    logger.warning(
                        "ocr skipped a page", extra={"page": index + 1, "why": exc.message}
                    )
                    skipped.append(index + 1)
                    continue
                layer = texts[index]
                # OCR replaces the text layer only when it read more than the layer holds.
                if len(result.text.strip()) <= len(layer.strip()):
                    continue
                markdown = _swap_in_markdown(markdown, layer, result.text)
                texts[index] = result.text
                used.append(index + 1)
                if result.mean_confidence < OCR_LOW_CONFIDENCE:
                    low.append(index + 1)
        finally:
            await asyncio.to_thread(pdf.close)
    return ParsedDocument(
        markdown=markdown,
        page_texts=texts,
        ocr_pages=tuple(used),
        ocr_low_confidence_pages=tuple(low),
        ocr_skipped_pages=tuple(sorted(skipped)),
    )


def _render(pdf: Any, index: int, dpi: int) -> Image.Image:
    return cast(Image.Image, pdf.pages[index].to_image(resolution=dpi).original)


def _swap_in_markdown(markdown: str, layer: str, ocr_text: str) -> str:
    # ponytail: exact-match swap, else append; ceiling is OCR text landing at
    # the end of the document rather than in page order when markitdown's text differs.
    layer = layer.strip()
    if layer and layer in markdown:
        return markdown.replace(layer, ocr_text, 1)
    return f"{markdown}\n\n{ocr_text}".strip()


async def _parse_image(data: bytes, engine: OcrEngine | None) -> ParsedDocument:
    if engine is None:
        raise IngestError("OCR is disabled, so this image cannot be read")
    settings = get_settings()
    try:
        image = await asyncio.to_thread(_open_image, data)
        async with ocr_gate():
            result: OcrPage = await engine.recognize(
                image, languages=check_languages(settings.ocr_languages)
            )
    except OcrError as exc:
        raise IngestError(exc.message) from exc
    if not result.text.strip():
        raise IngestError("No text could be read from this image")
    return ParsedDocument(
        markdown=result.text,
        page_texts=[result.text],
        ocr_pages=(1,),
        ocr_low_confidence_pages=(1,) if result.mean_confidence < OCR_LOW_CONFIDENCE else (),
    )


def _open_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # decompression bomb, truncated or corrupt file
        raise IngestError("Could not read image") from exc
    return image


def _markitdown_text(data: bytes) -> str:
    result = MarkItDown().convert(io.BytesIO(data))
    return cast(str, getattr(result, "text_content", ""))


def _pdf_page_texts(data: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def _image_coverage(data: bytes) -> list[float]:
    """Fraction of each page covered by embedded images (clipped to the page)."""
    coverage: list[float] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            area = float(page.width * page.height) or 1.0
            covered = 0.0
            try:
                for img in page.images:
                    width = min(img["x1"], page.width) - max(img["x0"], 0)
                    height = min(img["bottom"], page.height) - max(img["top"], 0)
                    covered += max(width, 0) * max(height, 0)
            except Exception:
                covered = 0.0
            coverage.append(min(covered / area, 1.0))
    return coverage


def _pdf_text(data: bytes) -> str:
    return "\n\n".join(_pdf_page_texts(data))
