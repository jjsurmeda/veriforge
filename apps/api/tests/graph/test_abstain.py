from collections.abc import AsyncIterator

import pytest
from pytest import MonkeyPatch

from graph.abstain import (
    build_abstain_event,
    build_abstain_template,
    stream_abstention,
)
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


async def _echo_prompt(*, messages: list[dict[str, str]], **_: object) -> AsyncIterator[str]:
    yield "\n".join(m["content"] for m in messages)


async def _never_called(**_: object) -> AsyncIterator[str]:
    raise AssertionError("the LLM must not be called for an English question")
    yield ""  # pragma: no cover - unreachable, keeps this an async generator


async def _render(
    question: str, *, offered_actions: list[str] | None = None
) -> tuple[str, list[dict[str, str]]]:
    """Render one abstention, returning the text and the messages sent."""
    sent: list[dict[str, str]] = []

    async def spy(**kwargs: object) -> AsyncIterator[str]:
        sent.extend(kwargs["messages"])  # type: ignore[arg-type]
        yield "<<translated>>"

    event = build_abstain_event("run", [], offered_actions=offered_actions or [])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("graph.abstain.stream_completion", spy)
        text = "".join(
            [
                part
                async for part in stream_abstention(
                    event, litellm_model="m", question=question, metadata={}
                )
            ]
        )
    return text, sent


async def test_abstention_uses_section_headings_and_toggle_names() -> None:
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


async def test_a_document_name_in_another_script_survives_untouched() -> None:
    """Language comes from the question only — a Han or Cyrillic document
    name must not drag the decline into that language."""
    event = build_abstain_event("run", [_chunk(page=3, heading_path=None)], offered_actions=[])
    text = "".join(
        [
            part
            async for part in stream_abstention(
                event,
                litellm_model="m",
                question="Who wrote Cien años de soledad?",
                metadata={},
            )
        ]
    )

    assert text == build_abstain_template(event)


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


async def test_english_question_skips_the_llm_and_returns_the_template(
    monkeypatch: MonkeyPatch,
) -> None:
    """The bug (C3): the decline came back in Turkish for every question.
    English needs no translation, so there is no call to get wrong."""
    monkeypatch.setattr("graph.abstain.stream_completion", _never_called)
    event = build_abstain_event("run", [], offered_actions=["web", "deep"])
    text = "".join(
        [
            part
            async for part in stream_abstention(
                event,
                litellm_model="m",
                question="What does Walt Whitman find distinct?",
                metadata={},
            )
        ]
    )

    assert text == build_abstain_template(event)
    assert "I could not find enough evidence to answer that question." in text
    # The Turkish failure mode came with this trailing model aside; make sure
    # the English path cannot produce one.
    assert "Eğitim verileriniz" not in text


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("¿Quién escribió Cien años de soledad?", "Spanish"),
        ("Comment meurt Emma Bovary ?", "French"),
        ("In was verwandelt sich Gregor Samsa?", "German"),
        ("孫悟空の兵器は何か？", "Japanese"),
    ],
)
async def test_non_english_question_names_the_target_language(
    question: str,
    expected: str,
) -> None:
    _, sent = await _render(question)

    system, user = sent
    flat = " ".join(system["content"].split())
    assert f"render the fixed message below into {expected}" in flat
    assert "the language of their question" not in system["content"]
    # The question goes in the user message, where a model actually reads it —
    # labelled, so it is read as the message's origin and not as a request.
    assert question in user["content"]
    assert "Do not answer the question." in user["content"]
    assert "I could not find enough evidence" in system["content"]
