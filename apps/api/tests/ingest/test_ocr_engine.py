from __future__ import annotations

import asyncio
import shutil

import pytest
from PIL import Image, ImageDraw, ImageFont
from pytest import MonkeyPatch

from admin.service import _validate_settings
from errors import AppError
from ingest.ocr import (
    OCR_ENGINES,
    OcrError,
    OcrTimeout,
    OcrUnavailable,
    TesseractEngine,
    check_languages,
    get_ocr_engine,
    parse_tsv,
)
from runtime import DEFAULT_DATA

HEADER = "\t".join(
    [
        "level",
        "page_num",
        "block_num",
        "par_num",
        "line_num",
        "word_num",
        "left",
        "top",
        "width",
        "height",
        "conf",
        "text",
    ]
)


def _row(block: int, par: int, line: int, word: int, conf: float, text: str) -> str:
    return f"5\t1\t{block}\t{par}\t{line}\t{word}\t0\t0\t1\t1\t{conf}\t{text}"


TSV = "\n".join(
    [
        HEADER,
        "4\t1\t1\t1\t1\t0\t0\t0\t1\t1\t-1\t",
        _row(1, 1, 1, 1, 96, "Hello"),
        _row(1, 1, 1, 2, 90, "world"),
        _row(1, 1, 2, 1, 80, "again"),
        _row(2, 1, 1, 1, 10, "noise"),
        _row(2, 1, 1, 2, 70, "Second"),
    ]
)


def test_registry_holds_only_tesseract() -> None:
    assert list(OCR_ENGINES) == ["tesseract"]


def test_unknown_engine_errors_clearly() -> None:
    with pytest.raises(OcrError, match="'paddle' is unknown"):
        get_ocr_engine("paddle")


def test_setting_validates_against_the_registry() -> None:
    data = {**DEFAULT_DATA, "ocr": {"engine": "tesseract"}}
    _validate_settings(data)
    with pytest.raises(AppError) as err:
        _validate_settings({**data, "ocr": {"engine": "paddle"}})
    assert err.value.status_code == 422


def test_parse_tsv_text_and_confidence() -> None:
    page = parse_tsv(TSV, min_confidence=30)
    assert page.text == "Hello world\nagain\n\nSecond"
    assert page.word_count == 5 - 1
    assert page.mean_confidence == pytest.approx((96 + 90 + 80 + 10 + 70) / 5)


def test_language_whitelist_rejects_injection() -> None:
    assert check_languages("eng+chi_sim") == "eng+chi_sim"
    for bad in ("eng;rm -rf /", "eng+$(id)", "../eng", ""):
        with pytest.raises(OcrError):
            check_languages(bad)


class _FakeProcess:
    def __init__(self, stdout: bytes, hang: bool = False) -> None:
        self.returncode = 0
        self.killed = False
        self._stdout = stdout
        self._hang = hang

    async def communicate(self, _input: bytes) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(10)
        return self._stdout, b""

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return 0


def _patch_process(monkeypatch: MonkeyPatch, process: _FakeProcess) -> list[tuple[object, ...]]:
    seen: list[tuple[object, ...]] = []

    async def fake_exec(*args: object, **_kw: object) -> _FakeProcess:
        seen.append(args)
        return process

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/tesseract")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return seen


async def test_adapter_runs_binary_without_shell_and_parses(monkeypatch: MonkeyPatch) -> None:
    seen = _patch_process(monkeypatch, _FakeProcess(TSV.encode()))
    page = await TesseractEngine(5, 30).recognize(Image.new("RGB", (4, 4)), languages="eng+spa")
    assert page.text.startswith("Hello world")
    assert seen[0][:6] == ("/usr/bin/tesseract", "stdin", "stdout", "-l", "eng+spa", "tsv")


async def test_timeout_kills_the_subprocess(monkeypatch: MonkeyPatch) -> None:
    process = _FakeProcess(b"", hang=True)
    _patch_process(monkeypatch, process)
    with pytest.raises(OcrTimeout):
        await TesseractEngine(0.05, 30).recognize(Image.new("RGB", (4, 4)), languages="eng")
    assert process.killed


async def test_missing_binary_is_unavailable(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(OcrUnavailable):
        await TesseractEngine(5, 30).recognize(Image.new("RGB", (4, 4)), languages="eng")


async def test_bad_languages_never_reach_the_command_line(monkeypatch: MonkeyPatch) -> None:
    seen = _patch_process(monkeypatch, _FakeProcess(TSV.encode()))
    with pytest.raises(OcrError):
        await TesseractEngine(5, 30).recognize(Image.new("RGB", (4, 4)), languages="eng;rm -rf")
    assert seen == []


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
async def test_real_binary_reads_a_known_sentence() -> None:
    sentence = "The quick brown fox jumps over the lazy dog near the river bank"
    image = Image.new("RGB", (1400, 120), "white")
    ImageDraw.Draw(image).text((20, 30), sentence, fill="black", font=ImageFont.load_default(40))
    page = await TesseractEngine(30, 30).recognize(image, languages="eng")
    got = set(page.text.lower().split())
    want = set(sentence.lower().split())
    assert len(want & got) / len(want) >= 0.9
