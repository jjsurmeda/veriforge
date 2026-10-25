"""OCR for scanned PDF pages and uploaded images (beta, TRD §9.1).

To add an engine, in this one file: write a class with
`async def recognize(self, image, *, languages) -> OcrPage`, add one entry to
`OCR_ENGINES` (id, label, factory). The admin setting `ocr.engine` then accepts
the id; an unknown id is refused on save (422) and at ingest, never replaced
by a fallback. Compute only: OCR charges no credits.
"""

from __future__ import annotations

import asyncio
import io
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from PIL import Image

from config import get_settings
from errors import AppError

# The uploaded-image path decodes untrusted pixels; make the decompression-bomb
# limit explicit (about 90 megapixels) instead of relying on Pillow's default.
MAX_IMAGE_PIXELS = 90_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

# Tesseract language codes accepted in `ocr_languages` ("eng+spa"). Anything
# else never reaches the command line.
LANGUAGE_WHITELIST = frozenset(
    [
        "eng",
        "spa",
        "fra",
        "deu",
        "ita",
        "por",
        "nld",
        "rus",
        "ara",
        "hin",
        "chi_sim",
        "chi_tra",
        "jpn",
        "kor",
        "fil",
        "vie",
        "tha",
        "ind",
        "tur",
        "pol",
    ]
)
_CJK_GAP = re.compile(r"(?<=[぀-ヿ㐀-鿿]) (?=[぀-ヿ㐀-鿿])")


class OcrError(AppError):
    status_code = 422

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, status_code=422)


class OcrUnavailable(OcrError):
    """The engine cannot run here (binary missing). Pages are skipped and noted."""

    def __init__(self, why: str) -> None:
        super().__init__("ocr_unavailable", why)


class OcrTimeout(OcrError):
    def __init__(self) -> None:
        super().__init__("ocr_timeout", "OCR timed out on a page")


@dataclass(frozen=True)
class OcrPage:
    text: str
    mean_confidence: float
    word_count: int


class OcrEngine(Protocol):
    async def recognize(self, image: Image.Image, *, languages: str) -> OcrPage: ...


def check_languages(languages: str) -> str:
    bad = [code for code in languages.split("+") if code not in LANGUAGE_WHITELIST]
    if bad:
        raise OcrError("ocr_bad_languages", f"Unsupported OCR language code(s): {bad}")
    return languages


def parse_tsv(tsv: str, min_confidence: int) -> OcrPage:
    """Words (TSV level 5) under `min_confidence` are dropped; the mean is over
    every recognised word, so a noisy page still reads as noisy."""
    lines: dict[tuple[str, str, str], list[str]] = {}
    confidences: list[float] = []
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5" or not cols[11].strip():
            continue
        conf = float(cols[10])
        if conf < 0:
            continue
        confidences.append(conf)
        if conf >= min_confidence:
            lines.setdefault((cols[2], cols[3], cols[4]), []).append(cols[11].strip())
    out: list[str] = []
    previous: tuple[str, str] | None = None
    for (block, paragraph, _line), words in lines.items():
        if previous is not None and previous != (block, paragraph):
            out.append("")
        previous = (block, paragraph)
        out.append(_CJK_GAP.sub("", " ".join(words)))
    mean = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrPage("\n".join(out).strip(), mean, sum(len(w) for w in lines.values()))


class TesseractEngine:
    def __init__(self, timeout: float, min_confidence: int) -> None:
        self._timeout = timeout
        self._min_confidence = min_confidence

    async def recognize(self, image: Image.Image, *, languages: str) -> OcrPage:
        languages = check_languages(languages)
        binary = shutil.which("tesseract")
        if binary is None:
            raise OcrUnavailable("tesseract is not installed")
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        # Argument list, no shell. The image goes over stdin: no temp file to clean.
        process = await asyncio.create_subprocess_exec(
            binary,
            "stdin",
            "stdout",
            "-l",
            languages,
            "tsv",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(buffer.getvalue()), self._timeout
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise OcrTimeout() from exc
        if process.returncode != 0:
            raise OcrError("ocr_failed", f"tesseract exited with {process.returncode}")
        return parse_tsv(stdout.decode("utf-8", errors="replace"), self._min_confidence)


@dataclass(frozen=True)
class OcrEngineInfo:
    id: str
    label: str
    build: Callable[[], OcrEngine]


# ponytail: one dict, no plugin discovery; see the module docstring.
OCR_ENGINES: dict[str, OcrEngineInfo] = {
    info.id: info
    for info in (
        OcrEngineInfo(
            "tesseract",
            "Tesseract (local, text only; does not read ruled tables)",
            lambda: TesseractEngine(
                get_settings().ocr_page_timeout_seconds, get_settings().ocr_min_confidence
            ),
        ),
    )
}


def get_ocr_engine(engine_id: str) -> OcrEngine:
    """Build the configured engine or refuse by name. Never falls back."""
    info = OCR_ENGINES.get(engine_id)
    if info is None:
        raise OcrError("ocr_engine_unknown", f"OCR engine {engine_id!r} is unknown")
    return info.build()


_gate: asyncio.Semaphore | None = None


def ocr_gate() -> asyncio.Semaphore:
    """One OCR at a time per worker process: the box has 4 GB."""
    global _gate
    if _gate is None:
        _gate = asyncio.Semaphore(1)
    return _gate
