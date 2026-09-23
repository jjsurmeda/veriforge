"""Generate node (TRD §7): streams the grounded answer with [n] markers.

The generator has no tools and never sees unescaped instruction text —
sources are wrapped as quoted data (TRD §11); the real sanitizer and
structural-injection defence land in slice 4.
"""

from collections.abc import AsyncIterator

from prompts.load import load_prompt
from providers.llm import stream_completion
from retrieval.expand import ExpandedContext

SOURCE_MAX_CHARS = 6000


def _source_block(n: int, context: ExpandedContext) -> str:
    chunk = context.chunk
    header = f"[Source {n}]"
    if chunk.document_name:
        header += f" document: {chunk.document_name}"
    if chunk.page is not None:
        header += f" page: {chunk.page}"
    return f"{header}\n{context.context_text[:SOURCE_MAX_CHARS]}\n[/Source {n}]"


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
) -> AsyncIterator[str]:
    async for token in stream_completion(
        litellm_model=litellm_model,
        messages=build_grounded_messages(question, contexts, history),
        metadata=metadata,
    ):
        yield token
