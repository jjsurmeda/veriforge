"""Abstain node (TR-4): shared between Auto and Deep — both modes hit the
same fixed template and offered-actions list when evidence is insufficient
(graph/auto.py's single-hop path via `sufficient_retry`, graph/deep.py's
multi-hop path via the controller's E/H exit per TRD §7's flowchart)."""

from collections.abc import AsyncIterator

from retrieval.hybrid import ScoredChunk
from schemas.events import Abstain


def _location(chunk: ScoredChunk) -> str:
    return f"p.{chunk.page}" if chunk.page is not None else chunk.heading_path or "section"


def build_abstain_event(
    run_id: str, kept: list[ScoredChunk], *, offered_actions: list[str]
) -> Abstain:
    found = "\n".join(
        f"- {c.document_name or c.source_type} {_location(c)}" for c in kept[:3]
    ) or "(no sources found)"
    missing = (
        "The retrieved sources do not contain enough evidence to "
        "answer this question."
    )
    return Abstain(
        run_id=run_id,
        found_summary=found,
        missing_summary=missing,
        offered_actions=offered_actions,
    )


async def stream_abstention(abstain: Abstain) -> AsyncIterator[str]:
    """TR-4 fixed template: what was found (cited), what's missing, offer
    follow-up actions. The generator only renders the template — no LLM
    call is made for an abstention."""
    text = (
        "I could not find enough evidence to answer that question.\n\n"
        f"What I found:\n{abstain.found_summary}\n\n"
        f"What is missing:\n{abstain.missing_summary}\n\n"
        "You can try:\n"
    )
    if "web" in abstain.offered_actions:
        text += "- Turn on the Web search toggle\n"
    if "deep" in abstain.offered_actions:
        text += "- Turn on the Deep search toggle for multi-step reasoning across documents\n"
    yield text
