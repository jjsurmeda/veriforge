"""Sanitize stage (TRD §11 layer 4): ask which of the chunks that can reach
the generator carry an injection attempt.

It runs after rerank, so only the chunks in the top-k are asked about, and a
dropped chunk is not backfilled from beyond the reranked set — generation
simply sees fewer chunks.
"""

from __future__ import annotations

from functools import partial

from decisions.sanitize import sanitize_chunks
from graph.stages.common import decide_or_degrade, decision_event
from graph.stages.state import AutoRunState, StageEnv
from retrieval.hybrid import ScoredChunk


async def sanitize(
    env: StageEnv, state: AutoRunState, winners: list[ScoredChunk]
) -> tuple[list[ScoredChunk], list[ScoredChunk]]:
    """The chunks the generator may see, and the ones this attempt dropped,
    with the sanitizer's per-chunk answers recorded as decisions.

    A decision-layer outage degrades to "every chunk unanswered, every chunk
    dropped" rather than failing the run (KI-57) — see `decisions.sanitize` for
    why that is the branch and what it costs."""
    kept, dropped, answers = await env.step(
        "sanitize",
        partial(
            sanitize_chunks,
            env.engine,
            run_id=str(env.params.run_id),
            chunks=winners,
            degrade=partial(decide_or_degrade, env),
        ),
    )
    for name, answer in answers.items():
        state.decision_events.append(decision_event(env.params.run_id, name, answer))
    return kept, dropped
