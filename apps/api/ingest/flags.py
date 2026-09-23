from __future__ import annotations

from dataclasses import dataclass

LOW_TEXT_MIN_CHARS = 200
TABLE_MIN_CELLS = 12
PIPE_DENSITY_PER_1K = 25


@dataclass(frozen=True)
class PageScan:
    text: str
    table_cell_count: int = 0
    pipe_count: int = 0


def flag_pages(pages: list[PageScan]) -> list[dict[str, object]]:
    flagged: list[dict[str, object]] = []
    for index, page in enumerate(pages, start=1):
        flags: list[str] = []
        stripped_len = len(page.text.strip())
        if stripped_len < LOW_TEXT_MIN_CHARS:
            flags.append("low_text")
        if (
            page.table_cell_count >= TABLE_MIN_CELLS
            or _pipe_density(page.pipe_count, stripped_len) > PIPE_DENSITY_PER_1K
        ):
            flags.append("table_heavy")
        if flags:
            flagged.append({"page": index, "flags": flags})
    return flagged


def _pipe_density(pipe_count: int, char_count: int) -> float:
    return (pipe_count / max(char_count, 1)) * 1000
