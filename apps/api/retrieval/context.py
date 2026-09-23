"""Context budget and meter (TRD §9.2).

Expanded context is trimmed to 60% of the generator's window minus the
history; the meter reports what landed (used/window) for the metrics event.
"""

import litellm

from ingest.chunk import ENCODING_MODEL
from retrieval.expand import ExpandedContext

CONTEXT_WINDOW_FRACTION = 0.6


def count_tokens(text: str) -> int:
    return int(litellm.token_counter(model=ENCODING_MODEL, text=text))


def trim_context(
    contexts: list[ExpandedContext], *, window_tokens: int, history_tokens: int
) -> tuple[list[ExpandedContext], int]:
    """Keep whole contexts in rank order within budget; if the first doesn't
    fit, truncate it (approx 4 chars/token) rather than send nothing."""
    budget = max(0, int(CONTEXT_WINDOW_FRACTION * window_tokens) - history_tokens)
    kept: list[ExpandedContext] = []
    used = 0
    for context in contexts:
        tokens = count_tokens(context.context_text)
        if used + tokens <= budget:
            kept.append(context)
            used += tokens
            continue
        if not kept and budget > 0:
            truncated = context.context_text[: budget * 4]
            kept.append(ExpandedContext(context.chunk, truncated))
            used += count_tokens(truncated)
        break
    return kept, used
