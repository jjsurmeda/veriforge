"""Generate node (TRD §7): streams the grounded answer with [n] markers.

The generator has no tools and never sees unescaped instruction text --
sources are wrapped in structural `<source>` tags with ingestion-time
escaping of any such tags inside chunk text (TRD §11 layers 1-3).
"""

from collections.abc import AsyncIterator, Awaitable, Callable

from prompts.load import load_prompt
from providers.llm import stream_completion
from retrieval.expand import ExpandedContext
from runtime import runtime_value
from textkit import DEFAULT_LANGUAGE, detect_language, language_name

SOURCE_MAX_CHARS = 6000

# One block per ingress intent, keyed on what the run already decided.
# `rag-reference.md`'s "Generator prompt" row asks for per-intent instructions
# and the plan's R2 row for a "generator prompt per intent"; four blocks cover
# the intents that mean something different to an answer, and any other intent
# — including a new one ingress might grow — falls back to the base prompt.
#
# Each file lives in `prompts/` with its own version header, so a change to one
# block is a reviewable diff and is caught by the eval gate (CLAUDE.md).
INTENT_BLOCKS: dict[str, str] = {
    "lookup": "intent_lookup.md",
    "summarize": "intent_summarize.md",
    "compare": "intent_compare.md",
    "multi-part": "intent_multi_part.md",
}


def _escape_attr(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _source_block(n: int, context: ExpandedContext) -> str:
    chunk = context.chunk
    attrs = [f'id="{n}"']
    if chunk.document_name:
        attrs.append(f'doc="{_escape_attr(chunk.document_name)}"')
    if chunk.page is not None:
        attrs.append(f'page="{chunk.page}"')
    return f"<source {' '.join(attrs)}>\n{context.context_text[:SOURCE_MAX_CHARS]}\n</source>"


def build_grounded_messages(
    question: str,
    contexts: list[ExpandedContext],
    history: list[tuple[str, str]],
    intent: str | None = None,
    language: str | None = None,
) -> list[dict[str, str]]:
    system = grounded_system_prompt(intent)
    # KI-86: name a NON-English question's language up front (code, not a prompt file), so
    # streamed answers are covered too. English adds nothing, which keeps the measured
    # English prompt as it was (and a rewrite that turned a question into English cannot
    # force English on the user). An explicit `language` is the retry's.
    detected = detect_language(question)
    if language is None and detected and detected != DEFAULT_LANGUAGE:
        language = language_name(detected)
    if language:
        system += f"\n\nWrite the whole answer in {language}, the language of the question."
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for role, content in history[-6:]:
        messages.append({"role": role, "content": content})
    if contexts:
        # `contexts` is already in generation order (`order_for_lost_in_the_middle`,
        # applied once where the context is trimmed), so block n is the passage
        # citation n, the reviewer and IsUse name.
        sources = "\n\n".join(_source_block(i + 1, c) for i, c in enumerate(contexts))
        messages.append(
            {
                "role": "user",
                "content": f"{sources}\n\n[Question]\n{question}",
            }
        )
    else:
        messages.append(
            {
                "role": "user",
                "content": (
                    "No sources were retrieved for this question. State that "
                    "no sources are available and answer briefly that you "
                    "cannot ground an answer; suggest uploading documents "
                    f"covering it.\n\n[Question]\n{question}"
                ),
            }
        )
    return messages


def grounded_system_prompt(intent: str | None) -> str:
    """The base grounded prompt, plus the one block for this run's intent.

    The intent is the one ingress already decided, so this costs no extra model
    call — `rag-reference.md`'s "per-intent instructions" without a
    classifier in front of the generator. An intent with no block (including
    `chitchat`, which never reaches here, and anything ingress invents later)
    gets the base prompt alone, which is the safe default: an unknown shape is
    better answered by the general rules than by a guess about its shape.
    """
    base = load_prompt("grounded_answer.md")
    block = INTENT_BLOCKS.get(intent or "")
    if block is None:
        return base
    return f"{base}\n\n{load_prompt(block)}"


def order_for_lost_in_the_middle(contexts: list[ExpandedContext]) -> list[ExpandedContext]:
    """Put the strongest passages at the start and the end of the sources block.

    "Lost in the middle" is the well-measured position effect: a model
    attending to the edges of a long context uses what is at either end and
    under-uses what is between them. Rerank order puts the weakest passage
    *last*, where it is read most — the single most likely place for a
    rank-ordered sources block to lose the answer.

    `contexts` arrives in rerank order, best first. The permutation takes the
    best quarter to the front and the second-best quarter to the back, so both
    edges are strong and the middle holds the weakest material. Source ids are
    assigned after the permutation, and the permutation is applied ONCE, where
    the context is trimmed (`graph/stages/finish_stage.py`, `deep.py`, `fast.py`),
    so the prompt's `[n]`, the stored citation n, the reviewer's passage n and
    IsUse's source n are the same passage. Reordering inside the prompt builder
    alone would leave every one of those on the rank order.

    With fewer than four passages there is no "middle" to lose: everything is
    an edge, and any permutation would only move citations around, so the order
    is left alone.
    """
    if len(contexts) < 4:
        return list(contexts)
    best = contexts[: len(contexts) // 2]
    weakest = contexts[len(contexts) // 2 :]
    front = best[: max(1, len(best) // 2)]
    back = best[max(1, len(best) // 2) :]
    return [*front, *weakest, *reversed(back)]


async def stream_grounded_answer(
    *,
    litellm_model: str,
    question: str,
    contexts: list[ExpandedContext],
    history: list[tuple[str, str]],
    metadata: dict[str, str],
    intent: str | None = None,
    on_reasoning: Callable[[str], Awaitable[None]] | None = None,
    language: str | None = None,
    max_tokens: int | None = None,
    on_finish: Callable[[str], None] | None = None,
) -> AsyncIterator[str]:
    """Stream the grounded answer.

    The generator's temperature is read from the runtime setting
    `generation.temperature`, which is `null` by default, so nothing is sent
    and the provider default applies byte-for-byte as before. It is a
    runtime setting and not an env-only `Settings` field because it is a
    product-quality decision to be made on the full eval sets, which is
    exactly what an admin needs to change without a redeploy; every other
    tunable (reranker, thresholds, top_k) is already admin-settable and this
    one being not was an inconsistency. Answer variety is decided on the eval
    sets rather than here; claim extraction is pinned at 0 in
    `graph/review.py` because it is a parsing call, not a product choice.
    """
    async for token in stream_completion(
        litellm_model=litellm_model,
        messages=build_grounded_messages(question, contexts, history, intent, language),
        metadata={**metadata, "role": "generator"},
        on_reasoning=on_reasoning,
        temperature=runtime_value("generation.temperature", None),
        max_tokens=max_tokens,
        on_finish=on_finish,
    ):
        yield token


def build_chitchat_messages(
    message: str, history: list[tuple[str, str]]
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": load_prompt("chitchat.md")}
    ]
    for role, content in history[-4:]:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    return messages


async def stream_chitchat_reply(
    *,
    litellm_model: str,
    message: str,
    history: list[tuple[str, str]],
    metadata: dict[str, str],
) -> AsyncIterator[str]:
    """Small talk: a direct, sourceless reply. No retrieval, no citations, no
    reviewer (TRD §7 ingress row)."""
    async for token in stream_completion(
        litellm_model=litellm_model,
        messages=build_chitchat_messages(message, history),
        metadata={**metadata, "role": "generator"},
    ):
        yield token


def build_library_messages(
    question: str, names: list[str], history: list[tuple[str, str]]
) -> list[dict[str, str]]:
    listing = "\n".join(f"- {name}" for name in names)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": load_prompt("library.md")}
    ]
    for role, content in history[-4:]:
        messages.append({"role": role, "content": content})
    messages.append(
        {
            "role": "user",
            "content": (
                f"These {len(names)} document(s) are in the user's sources:\n"
                f"{listing or '(none)'}\n\n"
                f"[Question]\n{question}"
            ),
        }
    )
    return messages


async def stream_library_reply(
    *,
    litellm_model: str,
    question: str,
    names: list[str],
    history: list[tuple[str, str]],
    metadata: dict[str, str],
) -> AsyncIterator[str]:
    """A library question: answered from the scope's document list, so no
    retrieval, no citations and no reviewer (TRD §7 ingress row)."""
    async for token in stream_completion(
        litellm_model=litellm_model,
        messages=build_library_messages(question, names, history),
        metadata={**metadata, "role": "generator"},
    ):
        yield token
