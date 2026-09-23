from __future__ import annotations

from ingest.accept import sniff_mime


def test_sniff_mime_accepts_pdf_bytes() -> None:
    assert sniff_mime("paper.pdf", b"%PDF-1.7\n...") == "application/pdf"


def test_sniff_mime_accepts_zip_based_docx_by_filename() -> None:
    assert (
        sniff_mime("paper.docx", b"PK\x03\x04...")
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_sniff_mime_accepts_utf8_markdown() -> None:
    assert sniff_mime("notes.md", b"# Hello\n") == "text/markdown"


def test_sniff_mime_rejects_executable_and_unknown_binary() -> None:
    assert sniff_mime("run.exe", b"MZ...") is None
    assert sniff_mime("blob.bin", b"\x00\x01\x02") is None
