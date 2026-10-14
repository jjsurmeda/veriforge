"""Ingress stage (TRD §7): the greeting fast path, ingress and rewrite in
parallel, and the routes that end the run before any retrieval — small talk
with nothing to retrieve, a library listing, and a blocked message.

Returns the finished run for those routes, or None when the run continues into
retrieval.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from uuid import UUID

from chats.scope import list_scope_documents
from db.models import Chat
from graph import rewrite as rewrite_node
from graph.history import history_messages
from graph.ingress import IngressOutcome, run_ingress
from graph.stages.checks import named_entities
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

# Whether a `chitchat` routing is worth retrieving for (KI-73).
#
# KI-71 made `chitchat` retrieve whenever the user had any source in scope, and
# let the evidence decide. That is right for a content question the classifier
# merely *phrased* like small talk — "tell me something about the adventures of
# sherlock holmes" is a question, not chit-chat, and the retrieval is the only
# thing that stops it being answered from memory.
#
# It is wrong for a message that names nothing at all. `smalltalk-thanks` —
# "thanks, that's helpful!" — retrieved the rewriter's prose about having no
# question, that retrieval cleared sufficiency, and the turn answered with
# eight citations. There was no question to be grounded in, so there was
# nothing for retrieval to do.
#
# So the rule is the brief's: a `chitchat` routing retrieves only when the
# user's own message names something. Two ways to name something, because
# `named_entities` alone is not enough and finding that out is worth writing
# down:
#
# 1. `named_entities(message)` — model codes and capitalised names. Catches
#    "¿Cómo se llama el caballo de Don Quijote?" and "tell me something about
#    the AW-2000 blade warranty".
# 2. A trailing lowercase proper name — two or more consecutive words at the
#    end of the message, none of them a stop word. This is what rule 1 cannot
#    see, and dropping it would be a regression, not a tightening: the recorded
#    `broad-sherlock` item is *"tell me something about the adventures of
#    sherlock holmes"*, lowercased throughout. A capitalisation heuristic alone
#    would have stopped it retrieving and turned a cited answer into the
#    uncited reply this product does not ship.
#
# Two words is not required, and that is deliberate: the two failure directions
# are not symmetric. Saying "no" to a content question turns a cited answer
# into the uncited reply this product does not ship — an acceptance-gate
# failure. Saying "yes" to a social turn costs one wasted fan-out and the
# sufficiency check still sends the run to the same small-talk reply it would
# have taken anyway. So the bar is one word, and the stop list below is what
# carries the judgement.
#
# The list is a **stop list of function, question and social words**, not a list
# of phrasings: it is how the trailing noun phrase is delimited, and it is not
# the greeting allowlist — nothing here changes which messages skip ingress
# entirely (CLAUDE.md's one carve-out, `greeting_canonical` above).
#
# "thanks, that's helpful!" and "awesome, thanks so much for that" are the two
# recorded shapes it has to end on a stop word; every plain acknowledgement
# ends on one, because acknowledgements end in a social particle.
_NON_NAME_WORDS = frozenset(
    {
        # The question's own frame: "what/who/how is X", "tell me about X".
        "a", "about", "an", "and", "any", "are", "anybody", "book", "can",
        "could", "did", "do", "does", "else", "for", "from", "get", "give",
        "has", "have", "he", "her", "him", "his", "how", "i", "in", "into",
        "is", "it", "its", "just", "know", "like", "made", "make", "many",
        "me", "much", "my", "of", "on", "or", "our", "please", "say", "she",
        "should", "some", "someone", "something", "such", "tell", "than",
        "that", "the", "their", "them", "then", "there", "they", "thing",
        "things", "this", "those", "to", "us", "very", "want", "was", "we",
        "were", "what", "when", "where", "which", "who", "whom", "whose",
        "why", "will", "with", "would", "you", "your",
        # Acknowledgement: the trailing word of a social turn. Every phrase in
        # GREETING_ALLOWLIST is here too, so this function answers the same
        # way about them as the fast path does — the fast path happens to get
        # there first, and a stop list that disagreed with it would be a trap
        # for the next reader. "rock" and "job" ("you rock", "good job") are
        # here for the same reason: a wasted fan-out is the cheap direction,
        # but there is no reason to pay for it.
        "afternoon", "appreciate", "appreciated", "awesome", "bye", "cool",
        "day", "evening", "good", "goodbye", "great", "hello", "helpful",
        "hey", "hi", "indeed", "job", "lot", "morning", "nice", "ok", "okay",
        "perfect", "rock", "thank", "thanks", "welcome",
        # Non-English question frames already in `checks._ENTITY_STOP`.
        "como", "cuál", "cual", "cómo", "dime", "dígame", "el", "la", "los",
        "las", "qué", "que", "quién", "quien", "cuándo", "cuando", "dónde",
        "donde", "por", "porqué", "über", "und",
    }
)
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def names_a_subject(message: str) -> bool:
    """Whether the user's own message names something to look up.

    See `_NON_NAME_WORDS` for why this is not simply `named_entities`.
    """
    if named_entities(message):
        return True
    words = _WORD.findall(message)
    for word in reversed(words):
        if word.lower() not in _NON_NAME_WORDS:
            return True
        break
    return False


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
    # `chitchat` takes the plain reply unless there is something to retrieve
    # AND something named to retrieve it for (KI-73): a message that names
    # nothing cannot be answered from a source, so paying for the fan-out only
    # buys the run a way to be confidently wrong about having no question.
    if state.chitchat_route and not (
        state.has_collections and names_a_subject(env.params.question)
    ):
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
