from graph.abstain import build_abstain_event, stream_abstention
from retrieval.hybrid import ScoredChunk


def _chunk(*, page: int | None, heading_path: str | None) -> ScoredChunk:
    from uuid import uuid4

    return ScoredChunk(
        chunk_id=uuid4(),
        document_id=None,
        document_name="Book.txt",
        section_id=None,
        ord=0,
        page=page,
        text="evidence",
        heading_path=heading_path,
        source_type="document",
        vector_score=None,
        bm25_score=None,
        fused_score=0.0,
    )


async def test_abstention_uses_section_headings_and_toggle_names() -> None:
    event = build_abstain_event(
        "run",
        [_chunk(page=None, heading_path="Chapter 34: The Proposal")],
        offered_actions=["web", "deep"],
    )
    text = "".join([part async for part in stream_abstention(event)])

    assert "Book.txt Chapter 34: The Proposal" in text
    assert "p.?" not in text
    assert "Web search toggle" in text
    assert "Deep search toggle" in text
    assert "source picker" not in text
