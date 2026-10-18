"""The scorer grades the text the user is left with (third-party review, 2026-10-19)."""

from scripts.smoke_chat import final_answer


def test_a_revision_or_a_retraction_replaces_the_streamed_draft() -> None:
    draft = "Julia Stoner died of fear and shock."
    retracted = "I could not find enough evidence to answer that question."
    assert final_answer(draft, [{"content": retracted, "status": "abstained"}]) == retracted

    revised = "Julia Stoner was killed by a swamp adder."
    assert final_answer(draft, [{"content": revised}]) == revised


def test_the_stream_is_only_the_fallback_when_the_message_cannot_be_read() -> None:
    assert final_answer("streamed text", []) == "streamed text"
    assert final_answer("streamed text", [{"content": ""}]) == "streamed text"
