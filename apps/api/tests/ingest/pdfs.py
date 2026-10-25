"""Tiny PDF builder for tests: text pages and pages with one embedded image."""

from __future__ import annotations

import io
import textwrap

from PIL import Image


def build_pdf(pages: list[tuple[str, float]]) -> bytes:
    """Each page is (text, image_fraction); the image is a grey block covering
    that fraction of the 612x792 page (0 means no image)."""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    add(b"")  # pages, patched below
    font = add(b"<< /Type /Font /Subtype /Font /BaseFont /Helvetica >>")
    kids: list[int] = []
    for text, fraction in pages:
        ops = b""
        res = f"/Font << /F1 {font} 0 R >>"
        if fraction > 0:
            height = 792 * fraction
            raw = bytes([128]) * 3 * 4
            img = add(
                b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceRGB "
                b"/BitsPerComponent 8 /Length 12 >>\nstream\n" + raw + b"\nendstream"
            )
            ops += f"q 612 0 0 {height} 0 0 cm /Im1 Do Q\n".encode()
            res += f" /XObject << /Im1 {img} 0 R >>"
        y = 780
        for line in textwrap.wrap(text, 90):
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops += f"BT /F1 9 Tf 20 {y} Td ({safe}) Tj ET\n".encode()
            y -= 11
        content = add(b"<< /Length %d >>\nstream\n" % len(ops) + ops + b"endstream")
        kids.append(
            add(
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content} 0 R "
                f"/Resources << {res} >> >>".encode()
            )
        )
    refs = " ".join(f"{k} 0 R" for k in kids)
    objs[1] = f"<< /Type /Pages /Count {len(kids)} /Kids [{refs}] >>".encode()
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    )
    return out.getvalue()


def png_bytes(image: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()
