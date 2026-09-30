"""Generate node (TRD §7): streams the grounded answer with [n] markers.

The generator has no tools and never sees unescaped instruction text --
sources are wrapped in structural `<source>` tags with ingestion-time
escaping of any such tags inside chunk text (TRD §11 layers 1-3).
"""

from collections.abc import AsyncIterator, Awaitable, Callable

from prompts.load import load_prompt
from providers.llm import stream_completion
from retrieval.expand import ExpandedContext

SOURCE_MAX_CHARS = 6000


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
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": load_prompt("grounded_answer.md")}
    ]
    for role, content in history[-6:]:
        messages.append({"role": role, "content": content})
    if contexts:
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


async def stream_grounded_answer(
    *,
    litellm_model: str,
    question: str,
    contexts: list[ExpandedContext],
    history: list[tuple[str, str]],
    metadata: dict[str, str],
    on_reasoning: Callable[[str], Awaitable[None]] | None = None,
) -> AsyncIterator[str]:
    async for token in stream_completion(
        litellm_model=litellm_model,
        messages=build_grounded_messages(question, contexts, history),
        metadata={**metadata, "role": "generator"},
        on_reasoning=on_reasoning,
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
