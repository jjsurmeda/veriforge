from __future__ import annotations

import io

import pytest
from PIL import Image
from pytest import MonkeyPatch

from config import get_settings
from ingest.accept import IngestError, sniff_mime
from ingest.chunk import chunk_document
from ingest.ocr import OcrPage, OcrUnavailable
from ingest.parse import PDF_MIME, _markitdown_text, _pdf_page_texts, parse_document
from ingest.pipeline import _with_ocr_flags
from tests.ingest.pdfs import build_pdf, png_bytes

DIGITAL = (
    "The harbour town of Alder Quay keeps its tide tables in a brass-bound ledger. "
    "Every dawn the clerk copies the high water mark onto a slate by the customs house. "
    "Fishermen read the slate before they untie their boats and trust it over any clock. "
)
OCR_TEXT = "Scanned ledger entry reading high water at six and low water at noon today."


class FakeEngine:
    def __init__(self, text: str = OCR_TEXT, confidence: float = 90.0) -> None:
        self.calls = 0
        self._page = OcrPage(text, confidence, len(text.split()))

    async def recognize(self, image: Image.Image, *, languages: str) -> OcrPage:
        self.calls += 1
        return self._page


async def test_digital_pdf_is_unchanged_and_never_calls_the_engine() -> None:
    data = build_pdf([(DIGITAL, 0), (DIGITAL + "More.", 0)])
    engine = FakeEngine()
    with_engine = await parse_document(PDF_MIME, data, engine=engine)
    without = await parse_document(PDF_MIME, data)
    assert engine.calls == 0
    assert with_engine == without
    # Byte-for-byte what the pre-OCR code produced.
    assert with_engine.markdown == _markitdown_text(data)
    assert with_engine.page_texts == _pdf_page_texts(data)
    assert with_engine.ocr_pages == () and with_engine.ocr_skipped_pages == ()
    assert len(with_engine.page_texts) == 2 and DIGITAL.strip()[:40] in with_engine.page_texts[0]


async def test_image_only_pdf_gets_engine_text_page_numbers_and_flag() -> None:
    data = build_pdf([("", 1.0)])
    parsed = await parse_document(PDF_MIME, data, engine=FakeEngine())
    assert parsed.page_texts == [OCR_TEXT]
    assert parsed.ocr_pages == (1,)
    chunks = [c for s in chunk_document(parsed.markdown, parsed.page_texts) for c in s.children]
    assert chunks and all(c.page == 1 and OCR_TEXT in c.text for c in chunks)
    flags = _with_ocr_flags([{"page": 1, "flags": ["low_text"]}], parsed)
    assert flags == [{"page": 1, "flags": ["low_text", "ocr"]}]


async def test_mixed_pdf_ocrs_only_its_scanned_pages() -> None:
    data = build_pdf([(DIGITAL, 0), ("", 1.0), (DIGITAL, 0)])
    engine = FakeEngine()
    parsed = await parse_document(PDF_MIME, data, engine=engine)
    assert engine.calls == 1
    assert parsed.ocr_pages == (2,)
    assert parsed.page_texts[1] == OCR_TEXT and parsed.page_texts[0] != OCR_TEXT
    assert OCR_TEXT in parsed.markdown and "Alder Quay" in parsed.markdown


async def test_image_plus_caption_page_over_200_chars_is_ocrd_by_coverage() -> None:
    # 60% image coverage with a 230+ char caption: not low_text, OCR'd on coverage.
    data = build_pdf([(DIGITAL, 0.6)])
    longer = "Figure text read from the picture itself. " * 8 + DIGITAL
    engine = FakeEngine(text=longer)
    parsed = await parse_document(PDF_MIME, data, engine=engine)
    assert engine.calls == 1 and parsed.ocr_pages == (1,)
    # A small figure (30%) leaves the text layer alone.
    small = await parse_document(PDF_MIME, build_pdf([(DIGITAL, 0.3)]), engine=engine)
    assert engine.calls == 1 and small.ocr_pages == ()


async def test_ocr_keeps_the_text_layer_when_it_reads_less() -> None:
    data = build_pdf([(DIGITAL, 0.9)])
    parsed = await parse_document(PDF_MIME, data, engine=FakeEngine(text="short"))
    assert parsed.ocr_pages == () and "Alder Quay" in parsed.page_texts[0]


async def test_low_confidence_page_is_flagged() -> None:
    engine = FakeEngine(confidence=40)
    parsed = await parse_document(PDF_MIME, build_pdf([("", 1.0)]), engine=engine)
    assert parsed.ocr_low_confidence_pages == (1,)
    assert "ocr_low_confidence" in _with_ocr_flags([], parsed)[0]["flags"]  # type: ignore[operator]


async def test_page_cap_skips_and_notes_the_rest(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "ocr_max_pages_per_document", 2)
    engine = FakeEngine()
    parsed = await parse_document(PDF_MIME, build_pdf([("", 1.0)] * 4), engine=engine)
    assert engine.calls == 2
    assert parsed.ocr_pages == (1, 2) and parsed.ocr_skipped_pages == (3, 4)


async def test_disabled_ocr_does_what_ingest_does_today_and_notes_skipped_pages() -> None:
    data = build_pdf([(DIGITAL, 0), ("", 1.0)])
    parsed = await parse_document(PDF_MIME, data, engine=None)
    assert parsed.ocr_pages == () and parsed.ocr_skipped_pages == (2,)
    assert _with_ocr_flags([], parsed) == [{"page": 2, "flags": ["ocr_skipped"]}]


async def test_missing_binary_skips_remaining_pages() -> None:
    class Missing:
        async def recognize(self, image: Image.Image, *, languages: str) -> OcrPage:
            raise OcrUnavailable("tesseract is not installed")

    parsed = await parse_document(PDF_MIME, build_pdf([("", 1.0)] * 2), engine=Missing())
    assert parsed.ocr_pages == () and parsed.ocr_skipped_pages == (1, 2)


async def test_image_upload_is_one_page_whose_ocr_text_is_the_document() -> None:
    data = png_bytes(Image.new("RGB", (40, 40), "white"))
    parsed = await parse_document("image/png", data, engine=FakeEngine())
    assert parsed.markdown == OCR_TEXT and parsed.page_texts == [OCR_TEXT]
    assert parsed.ocr_pages == (1,)


async def test_image_with_ocr_disabled_or_no_text_fails_clearly() -> None:
    data = png_bytes(Image.new("RGB", (40, 40), "white"))
    with pytest.raises(IngestError, match="disabled"):
        await parse_document("image/png", data, engine=None)
    with pytest.raises(IngestError, match="No text"):
        await parse_document("image/png", data, engine=FakeEngine(text=""))
    with pytest.raises(IngestError, match="Could not read"):
        await parse_document("image/png", b"not an image", engine=FakeEngine())


def test_images_are_sniffed_by_content_and_renamed_text_is_refused() -> None:
    img = Image.new("RGB", (8, 8), "white")
    for fmt, mime in (("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")):
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        assert sniff_mime("scan.bin", buf.getvalue()) == mime
    assert sniff_mime("notes.png", b"plain text pretending to be a picture") is None


async def test_engine_resolution_follows_setting_and_never_falls_back(
    monkeypatch: MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager

    from ingest import pipeline
    from ingest.ocr import OcrError, TesseractEngine
    from runtime import RuntimeSettings

    engine_id = {"value": "tesseract"}

    @asynccontextmanager
    async def fake_session():  # type: ignore[no-untyped-def]
        yield None

    async def fake_runtime(_session: object) -> RuntimeSettings:
        return RuntimeSettings.from_data(1, {"ocr": {"engine": engine_id["value"]}})

    monkeypatch.setattr(pipeline, "get_session_factory", lambda: fake_session)
    monkeypatch.setattr(pipeline, "load_active_runtime", fake_runtime)
    assert isinstance(await pipeline._ocr_engine(), TesseractEngine)
    engine_id["value"] = "paddle"
    with pytest.raises(OcrError, match="unknown"):
        await pipeline._ocr_engine()
    monkeypatch.setattr(get_settings(), "ocr_enabled", False)
    assert await pipeline._ocr_engine() is None
