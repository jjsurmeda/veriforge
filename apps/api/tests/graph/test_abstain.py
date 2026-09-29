from collections.abc import AsyncIterator

from pytest import MonkeyPatch

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


async def _echo_prompt(
    *, messages: list[dict[str, str]], **_: object
) -> AsyncIterator[str]:
    yield "\n".join(m["content"] for m in messages)


async def test_abstention_uses_section_headings_and_toggle_names(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr("graph.abstain.stream_completion", _echo_prompt)
    event = build_abstain_event(
        "run",
        [_chunk(page=None, heading_path="Chapter 34: The Proposal")],
        offered_actions=["web", "deep"],
    )
    text = "".join(
        [
            part
            async for part in stream_abstention(
                event, litellm_model="m", question="What did Darcy say?", metadata={}
            )
        ]
    )

    assert "Book.txt Chapter 34: The Proposal" in text
    assert "p.?" not in text
    assert "Web search toggle" in text
    assert "Deep search toggle" in text
    assert "source picker" not in text


async def test_abstention_names_the_documents_the_sources_cover() -> None:
    event = build_abstain_event(
        "run",
        [
            _chunk(page=1, heading_path=None),
            _chunk(page=2, heading_path=None),
        ],
        offered_actions=[],
    )

    assert "Your sources cover Book.txt." in event.found_summary


async def test_abstention_prompt_carries_the_language_rule(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("graph.abstain.stream_completion", _echo_prompt)
    event = build_abstain_event("run", [], offered_actions=[])
    text = "".join(
        [
            part
            async for part in stream_abstention(
                event, litellm_model="m", question="¿Qué dice Darcy?", metadata={}
            )
        ]
    )

    assert "in the language of" in text
    assert "¿Qué dice Darcy?" in text
    assert "I could not find enough evidence" in text
