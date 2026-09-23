from __future__ import annotations

from ingest.flags import PageScan, flag_pages


def test_flag_pages_low_text_boundary() -> None:
    assert flag_pages([PageScan(text="x" * 199)]) == [
        {"page": 1, "flags": ["low_text"]}
    ]
    assert flag_pages([PageScan(text="x" * 200)]) == []


def test_flag_pages_table_cell_boundary() -> None:
    assert flag_pages([PageScan(text="x" * 200, table_cell_count=11)]) == []
    assert flag_pages([PageScan(text="x" * 200, table_cell_count=12)]) == [
        {"page": 1, "flags": ["table_heavy"]}
    ]


def test_flag_pages_pipe_density_boundary() -> None:
    assert flag_pages([PageScan(text=("|" * 5) + ("x" * 195), pipe_count=5)]) == []
    assert flag_pages([PageScan(text=("|" * 6) + ("x" * 194), pipe_count=6)]) == [
        {"page": 1, "flags": ["table_heavy"]}
    ]
