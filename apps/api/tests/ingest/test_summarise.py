"""Summarisation (TRD §9.1 step 6): what the summariser is asked for, what it
refuses to return, and what ingest does with a failure.

The fake `complete` answers with a canned object and records the request, so
nothing here reaches a model (testing.md). What is asserted is the contract:

* **one call per document, both levels.** Two prompts would be two round trips
  and a document summary not in step with its sections.
* **the document summary is built from section summaries.** The prompt hands it
  summaries, not the chapter text — that is the cost and the quality decision
  recorded in `ingest/summarise.py`, and a prompt that quietly went back to the
  raw text would spend several times the credit for the same shape.
* **it refuses rather than guesses.** A section with no summary is a silent gap
  in the index; a document with no summary defeats the second level. Both are
  named failures.
* **ingest survives a summarisation failure.** The document is already indexed
  and usable; the backfill picks the summaries up. An ingest that failed here
  would make an already-uploaded document unreadable, which is worse than a
  corpus that is half-covered.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ingest.summarise import (
    DOCUMENT_INPUT_SECTIONS,
    SECTION_INPUT_CHARS,
    SUMMARY_ROLE,
    SummaryError,
    build_summary_prompt,
    parse_summaries,
    summarise_document,
)

SECTIONS: list[tuple[int, str, str]] = [
    (1, "Chapter 1", "A war surgeon settles in London and shares rooms with a detective."),
    (2, "Chapter 2", "They investigate a murder that the police have already closed."),
    (3, "", "The mystery deepens and an old enemy of Holmes reappears."),
]


def _reply(*, drop_section: int | None = None, no_document: bool = False) -> str:
    payload: dict[str, Any] = {
        "sections": {
            str(ord_): f"Summary of section {ord_}." for ord_, _, _ in SECTIONS
        },
        "document": "A detective and his doctor friend solve crimes in London.",
    }
    if drop_section is not None:
        payload["sections"].pop(str(drop_section))
    if no_document:
        payload.pop("document")
    return json.dumps(payload)


# --- the prompt ---------------------------------------------------------------


def test_the_prompt_asks_for_one_object_with_both_levels() -> None:
    prompt = build_summary_prompt(document_title="A Study in Scarlet", sections=SECTIONS)

    assert "A Study in Scarlet" in prompt
    assert '"sections"' in prompt and '"document"' in prompt
    assert prompt.count("--- section ") == len(SECTIONS)
    assert prompt.rstrip().endswith("no others. Ground every statement in the text you were given.")


def test_the_prompt_hands_the_document_level_its_inputs_not_the_raw_text() -> None:
    """Both levels share one call, so this is a property of the *prompt*: it
    describes one object, one section block per section, and one document-level
    instruction — and the only per-section material it carries is the section's
    own text. A prompt that appended a second 'here is the whole document, now
    summarise it' would pass a length check and cost several times the credit.
    """
    prompt = build_summary_prompt(document_title="A Study in Scarlet", sections=SECTIONS)

    # One question about the whole document, phrased once.
    assert prompt.lower().count("arc it follows") == 1
    assert "what this document is and" in prompt


def test_a_long_section_is_capped_rather_than_being_the_whole_prompt() -> None:
    # A filler that cannot appear in the prompt's own instructions, so the count
    # measures the section body and nothing else.
    filler = "BODY"
    huge = [(1, "Chapter 1", filler * 100_000)]

    prompt = build_summary_prompt(document_title="Big", sections=huge)

    assert prompt.count(filler) <= SECTION_INPUT_CHARS // len(filler)
    assert len(prompt) < SECTION_INPUT_CHARS + 2_000, (
        "a pathological section must not become the prompt"
    )


def test_a_document_with_more_sections_than_the_cap_is_truncated_sayably() -> None:
    """Thirty-two covers every book in this corpus. Beyond it the prompt says
    which sections it got, so the parser and the operator both know the document
    summary was built from a prefix rather than silently believing otherwise."""
    many = [(i, f"Chapter {i}", f"Body {i}.") for i in range(DOCUMENT_INPUT_SECTIONS + 20)]

    prompt = build_summary_prompt(document_title="Manual", sections=many)

    assert prompt.count("--- section ") == DOCUMENT_INPUT_SECTIONS
    assert f"each of the {DOCUMENT_INPUT_SECTIONS} section numbers" in prompt


# --- parsing ------------------------------------------------------------------


def test_a_good_reply_becomes_one_summary_per_section_plus_one_for_the_document() -> None:
    result = parse_summaries(_reply(), SECTIONS)

    assert [s.section_ord for s in result.sections] == [1, 2, 3]
    assert result.sections[0].heading_path == "Chapter 1"
    assert result.sections[2].heading_path == "", "an untitled section keeps an empty path"
    assert result.document.startswith("A detective")


def test_a_fenced_reply_is_accepted() -> None:
    """Providers wrap JSON in a fence even when asked not to; the fence is not a
    failure and treating it as one costs a whole document's summaries."""
    assert parse_summaries(f"```json\n{_reply()}\n```", SECTIONS).document


def test_a_missing_section_summary_is_a_named_failure() -> None:
    """Not skipped silently. One absent section is a hole in the index that only
    a gist question about that chapter would ever notice."""
    with pytest.raises(SummaryError, match="no summary for section 2"):
        parse_summaries(_reply(drop_section=2), SECTIONS)


def test_a_missing_document_summary_is_a_named_failure() -> None:
    with pytest.raises(SummaryError, match="no document summary"):
        parse_summaries(_reply(no_document=True), SECTIONS)


def test_prose_where_json_belongs_is_a_named_failure() -> None:
    with pytest.raises(SummaryError, match="non-JSON"):
        parse_summaries("I'd be happy to summarise that for you.", SECTIONS)


def test_a_json_array_where_an_object_belongs_is_a_named_failure() -> None:
    with pytest.raises(SummaryError, match="non-object JSON"):
        parse_summaries("[1, 2, 3]", SECTIONS)


def test_an_empty_section_summary_counts_as_missing() -> None:
    """Whitespace is not a summary, and writing one would put an empty row in
    the index that retrieval can rank and a citation can point at."""
    payload = json.loads(_reply())
    payload["sections"]["1"] = "   "
    with pytest.raises(SummaryError, match="no summary for section 1"):
        parse_summaries(json.dumps(payload), SECTIONS)


# --- the call ------------------------------------------------------------------


async def test_one_call_per_document_covers_both_levels() -> None:
    calls: list[dict[str, Any]] = []

    async def fake_complete(**kwargs: Any) -> str:
        calls.append(kwargs)
        return _reply()

    result = await summarise_document(
        document_title="A Study in Scarlet",
        sections=SECTIONS,
        small_model="openrouter/openai/gpt-4o-mini",
        complete_fn=fake_complete,
    )

    assert len(calls) == 1, "two prompts would be two round trips"
    assert len(result.sections) == len(SECTIONS)
    assert result.document


async def test_the_call_uses_the_small_model_role_and_pins_temperature() -> None:
    calls: list[dict[str, Any]] = []

    async def fake_complete(**kwargs: Any) -> str:
        calls.append(kwargs)
        return _reply()

    await summarise_document(
        document_title="A Study in Scarlet",
        sections=SECTIONS,
        small_model="openrouter/openai/gpt-4o-mini",
        complete_fn=fake_complete,
    )

    assert calls[0]["metadata"]["role"] == SUMMARY_ROLE
    assert calls[0]["temperature"] == 0, (
        "a summarisation whose text is indexed should not be stochastic"
    )


async def test_a_document_with_no_sections_is_refused_before_any_call() -> None:
    """Nothing to summarise is a caller error, not a provider call: an empty
    section list means the chunker produced nothing, and spending a call to be
    told so hides that."""
    calls: list[int] = []

    async def fake_complete(**_: Any) -> str:
        calls.append(1)
        return _reply()

    with pytest.raises(SummaryError, match="no sections"):
        await summarise_document(
            document_title="Empty",
            sections=[],
            small_model="openrouter/openai/gpt-4o-mini",
            complete_fn=fake_complete,
        )
    assert calls == []


async def test_an_unparseable_reply_raises_out_of_the_summariser() -> None:
    """The caller decides what an unusable reply means. Here it is an
    `IngestError`-shaped failure the pipeline logs and moves past; the point is
    that it is raised rather than returned as empty summaries, which would look
    like success."""

    async def fake_complete(**_: Any) -> str:
        return "sorry"

    with pytest.raises(SummaryError):
        await summarise_document(
            document_title="A Study in Scarlet",
        sections=SECTIONS,
        small_model="openrouter/openai/gpt-4o-mini",
        complete_fn=fake_complete,
        )
