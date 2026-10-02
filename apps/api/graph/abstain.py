"""Abstain node (TR-4): shared between Auto and Deep — both modes hit the
same fixed template and offered-actions list when evidence is insufficient
(graph/auto.py's single-hop path via `sufficient_abstain`, graph/deep.py's
multi-hop path via the controller's E/H exit per TRD §7's flowchart)."""

from collections.abc import AsyncIterator

from prompts.load import load_prompt
from providers.llm import stream_completion
from retrieval.hybrid import ScoredChunk
from schemas.events import Abstain
from textkit import DEFAULT_LANGUAGE, detect_language, language_name


def _location(chunk: ScoredChunk) -> str:
    return f"p.{chunk.page}" if chunk.page is not None else chunk.heading_path or "section"


def build_abstain_event(
    run_id: str, kept: list[ScoredChunk], *, offered_actions: list[str]
) -> Abstain:
    covers: list[str] = []
    for chunk in kept:
        name = chunk.document_name or chunk.source_type
        if name not in covers:
            covers.append(name)
    coverage = f"Your sources cover {', '.join(covers[:4])}." if covers else ""
    locations = (
        "\n".join(f"- {c.document_name or c.source_type} {_location(c)}" for c in kept[:3])
        or "(no sources found)"
    )
    found = "\n".join(part for part in (coverage, locations) if part)
    missing = "The retrieved sources do not contain enough evidence to answer this question."
    return Abstain(
        run_id=run_id,
        found_summary=found,
        missing_summary=missing,
        offered_actions=offered_actions,
    )


def build_abstain_template(abstain: Abstain) -> str:
    """The fixed English decline text. Shared by both output paths below."""
    template = (
        "I could not find enough evidence to answer that question.\n\n"
        f"What I found:\n{abstain.found_summary}\n\n"
        f"What is missing:\n{abstain.missing_summary}\n\n"
        "You can try:\n"
    )
    if "web" in abstain.offered_actions:
        template += "- Turn on the Web search toggle\n"
    if "deep" in abstain.offered_actions:
        template += "- Turn on the Deep search toggle for multi-step reasoning across documents\n"
    return template


async def stream_abstention(
    abstain: Abstain,
    *,
    litellm_model: str,
    question: str,
    metadata: dict[str, str],
) -> AsyncIterator[str]:
    """TR-4: the fixed template is generated here; the generator only
    renders it, in the language of the user's question (round 2, owner
    decision) — it does not write free-form text.

    An English question gets the template verbatim and no model call at all:
    the template is already English, so there is nothing to translate, and a
    gpt-4o-mini asked to "render this in the language of their question"
    answered Turkish for English *and* Spanish questions (C3, `.data/
    acceptance/20260929-194405.json`) — the vague target plus a question
    buried in the system prompt was enough to lose it.
    """
    template = build_abstain_template(abstain)
    language = detect_language(question)
    if language is None or language == DEFAULT_LANGUAGE:
        yield template
        return
    name = language_name(language)
    prompt = load_prompt("abstain.md").format(language=name, message=template)
    async for token in stream_completion(
        litellm_model=litellm_model,
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                # Labelled so the question is read as the source of the
                # message, not as something to answer: sent bare, the model
                # translated the template for one question and answered the
                # next one instead.
                "content": (
                    "The user's question was:\n\n"
                    f"{question}\n\n"
                    f"Translate the message in your instructions into {name}. "
                    "Do not answer the question."
                ),
            },
        ],
        metadata={**metadata, "role": "generator"},
    ):
        yield token
