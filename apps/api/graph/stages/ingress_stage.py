"""Ingress stage (TRD §7): the greeting fast path, ingress and rewrite in
parallel, and the routes that end the run before any retrieval — small talk
with nothing to retrieve, a library listing, and a blocked message.

Returns the finished run for those routes, or None when the run continues into
retrieval.
"""

from __future__ import annotations

import asyncio
import unicodedata
from uuid import UUID

from chats.scope import list_scope_documents
from db.models import Chat
from graph import rewrite as rewrite_node
from graph.history import history_messages
from graph.ingress import IngressOutcome, run_ingress
from graph.stages.common import decision_event, no_call
from graph.stages.state import AutoRun, AutoRunState, StageEnv
from schemas.events import Abstain

# The greeting fast path is the one approved exception to "all classification
# goes through DecisionEngine" (CLAUDE.md): a raw message of at most 40 chars
# whose normalised form is one of these phrases skips ingress and retrieval
# entirely. The generator only ever sees the CANONICAL phrase from this set,
# never the raw text, so invisible-character smuggling (zero-width, Unicode tag
# characters) cannot reach the model.
GREETING_ALLOWLIST = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "thanks a lot",
        "bye",
        "goodbye",
        "good morning",
        "good afternoon",
        "good evening",
        "ok",
        "okay",
        "cool",
        "great",
    }
)
MAX_GREETING_CHARS = 40
MAX_GREETING_WORDS = 4


def greeting_canonical(raw: str) -> str | None:
    """The canonical allowlist phrase the raw message normalises to, or
    None. Non-letters become spaces (not deleted) before collapsing, so
    "g-o-o-d" stays four words and can never reassemble into a greeting."""
    if len(raw) > MAX_GREETING_CHARS:
        return None
    normalized = unicodedata.normalize("NFKC", raw).lower()
    letters = "".join(c if c.isalpha() or c.isspace() else " " for c in normalized)
    words = letters.split()
    if len(words) > MAX_GREETING_WORDS:
        return None
    candidate = " ".join(words)
    return candidate if candidate in GREETING_ALLOWLIST else None


async def load_state(env: StageEnv) -> AutoRunState:
    """The state every later stage starts from: the chat history, the rolling
    summary, and whether anything is in scope to retrieve."""
    chat = await env.session.get(Chat, env.params.chat_id)
    return AutoRunState(
        history=await history_messages(env.session, env.params.chat_id, env.params.message_id),
        summary=chat.summary if chat is not None else None,
        has_collections=bool(env.params.collection_ids),
        ingress=_greeting_outcome(),
        rewritten=env.params.question,
    )


def _greeting_outcome() -> IngressOutcome:
    """The stand-in outcome of the greeting fast path, which skips ingress:
    a small-talk run with every guard passing."""
    return IngressOutcome(
        intent="chitchat",
        source="upload",
        complexity="single",
        risk="low",
        lexical_weight=0.5,
        guard_injection="pass",
        guard_jailbreak="pass",
        guard_pii="pass",
        off_topic="pass",
    )


async def run_ingress_stage(env: StageEnv, state: AutoRunState) -> AutoRun | None:
    """Greeting fast path, then ingress + rewrite in parallel, then the
    routes that answer without retrieving."""
    canonical_greeting = greeting_canonical(env.params.question)
    if canonical_greeting is not None:
        await env.step("Greeting fast path: skipped ingress", no_call)
        return direct_run(env, state, canonical_greeting, chitchat=True)

    state.ingress, state.rewritten = await env.step(
        "ingress+rewrite", lambda: _ingress_and_rewrite(env, state)
    )
    state.chitchat_route = (
        state.ingress.intent == "chitchat" and state.ingress.off_topic != "block"
    )
    # Every route below answers from the RAW question, never the rewrite: the
    # rewrite is a search query and the reply is a message to a person.
    if state.chitchat_route and not state.has_collections:
        await env.step("Small talk: skipped retrieval", no_call)
        return direct_run(env, state, env.params.question, chitchat=True)

    if state.ingress.intent == "library":
        await env.step("Library: skipped retrieval", no_call)
        names = [
            document.name
            for document in await list_scope_documents(
                env.session, list(env.params.collection_ids)
            )
        ]
        return direct_run(env, state, env.params.question, library_names=names)

    if state.ingress.blocked:
        state.abstain_event = _blocked_abstain(env.params.run_id)
        return direct_run(env, state, env.params.question)
    return None


async def _ingress_and_rewrite(env: StageEnv, state: AutoRunState) -> tuple[IngressOutcome, str]:
    """Ingress and rewrite in one round trip (TRD §7)."""
    outcome, rewritten = await asyncio.gather(
        run_ingress(
            env.engine,
            run_id=env.params.run_id,
            user_message=env.params.question,
            has_collections=state.has_collections,
        ),
        rewrite_node.rewrite_query(
            question=env.params.question,
            history=state.history,
            summary=state.summary,
            small_model=env.params.small_model,
            complete_fn=env.seams.complete,
        ),
    )
    for name, answer in outcome.answers.items():
        state.decision_events.append(decision_event(env.params.run_id, name, answer))
    return outcome, rewritten


def _blocked_abstain(run_id: UUID) -> Abstain:
    return Abstain(
        run_id=str(run_id),
        found_summary="",
        missing_summary=(
            "This message was blocked because it appears to attempt "
            "to manipulate the assistant or extract hidden state."
        ),
        offered_actions=[],
    )


def direct_run(
    env: StageEnv,
    state: AutoRunState,
    rewritten: str,
    *,
    chitchat: bool = False,
    library_names: list[str] | None = None,
    keep_decisions: bool = True,
) -> AutoRun:
    """A run that cites nothing: no contexts, no citations, nothing asserted.

    `decision` events are kept where they exist so the trace shows the ingress
    questions that produced the route; the greeting fast path passes none,
    because it skipped ingress entirely. A run that DID retrieve and then fell
    back to the small-talk reply passes `keep_decisions=False`: its decisions
    and retrieval events belong to the evidence it is no longer answering from.
    """
    return AutoRun(
        params=env.params,
        history=state.history,
        contexts=[],
        kept_chunks=[],
        dropped_chunks=[],
        rewritten=rewritten,
        retrieval_events=[],
        decision_events=list(state.decision_events) if keep_decisions else [],
        conflict_event=None,
        abstain_event=state.abstain_event,
        latency_ms=env.latency_ms,
        context_used=0,
        ingress=state.ingress,
        seams=env.seams,
        chitchat=chitchat,
        library_names=library_names,
    )
