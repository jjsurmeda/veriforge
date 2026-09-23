from pytest import MonkeyPatch

import ingest.chunk as chunk


def _fake_tokens(*, model: str, text: str) -> int:
    del model
    return (len(text) + 3) // 4


def test_chunk_document_tracks_nested_heading_paths(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("ingest.chunk.litellm.token_counter", _fake_tokens)
    sections = chunk.chunk_document("# A\nintro\n## B\nbee\n### C\nsee\n## D\ndee", [])
    assert [section.heading_path for section in sections] == ["A", "A > B", "A > B > C", "A > D"]
    assert [section.text for section in sections] == ["intro", "bee", "see", "dee"]


def test_chunk_document_splits_sections_over_2000_tokens(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("ingest.chunk.litellm.token_counter", _fake_tokens)
    exact = chunk.chunk_document("# A\n" + ("x" * 8000), [])
    over = chunk.chunk_document("# A\n" + ("x" * 8001), [])

    assert len(exact) == 1
    assert exact[0].tokens == 2000
    assert len(over) == 2
    assert over[0].tokens == 2000
    assert over[1].tokens == 1


def test_chunk_document_child_window_and_overlap(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("ingest.chunk.litellm.token_counter", _fake_tokens)
    sections = chunk.chunk_document("x" * 2400, [])

    assert len(sections) == 1
    assert len(sections[0].children) == 2
    assert sections[0].children[0].text == "x" * 2000
    assert sections[0].children[1].text == "x" * 700


def test_chunk_document_short_section_single_child(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("ingest.chunk.litellm.token_counter", _fake_tokens)
    sections = chunk.chunk_document("short", [])

    assert len(sections) == 1
    assert sections[0].children == [chunk.ChunkDraft(ord=0, page=None, text="short")]


def test_chunk_document_empty_markdown(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("ingest.chunk.litellm.token_counter", _fake_tokens)
    assert chunk.chunk_document("   \n\n", []) == []
