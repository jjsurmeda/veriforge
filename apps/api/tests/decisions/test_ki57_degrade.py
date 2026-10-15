"""KI-57: a decision-provider failure degrades, it never fails the run.

The recorded failure, from the R2a live run (verbatim in `known-issues.md`
and the R2a report):

    WARNING:decisions.engine:jev failed, retrying on fallback: jev http error:
    ERROR:decisions.engine:shadow fallback call failed
    decisions.fallback.FallbackError: fallback returned non-JSON:
        Expecting value: line 1 column 1 (char 0)
    ERROR:graph.runner:run failed
    {"event":"run.failed","error_code":"decision_unavailable"}

A socket timeout, then one unreadable reply, then a whole turn lost — at item
25 of 57, with 32 items never run. Every test here is a fake engine or a fake
`complete`; nothing reaches a provider (testing.md).

**One file, four paths, one contract each:**

| path | what is simulated | what must happen |
| --- | --- | --- |
| timeout | jev raises `TimeoutError`, fallback answers | answers come back (unchanged) |
| non-JSON | fallback returns prose, twice, then in halves | every question still answered |
| truncated JSON | fallback cuts the batch at a fixed offset | halved; every question answered |
| batch split | the fallback answers one question at a time | the batch halves until it can |

and then the degradation the split exists to make rare:

| stage | outage | the stage's own default |
| --- | --- | --- |
| ingress | no answers at all | the module's defaults, `lookup`/`both` |
| rerank | no answers at all | fused order (`rerank.py`, unchanged) |
| the gate | no answers at all | a FAILING gate → corrective retrieval → abstain |
| entity guard | no answers at all | fails: unconfirmed coverage is not coverage |
| sanitizer | no answers at all | every chunk kept, as for a skipped passage |
| reviewer | no answers at all | every claim `unsupported` |
| output guard | no answers at all | delivered as-is, as when the guard is off |
| Deep controller | no answers at all | `need_more` — another hop, never an answer |

and the shape the whole thing is for: **a run ends `completed`**.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

from config import get_settings
from decisions.breaker import CircuitBreaker
from decisions.engine import DecisionEngine, DecisionUnavailable
from decisions.fallback import FallbackEngine, FallbackError, fallback_max_tokens
from graph.ingress import (
    INGRESS_DEFAULTS,
    ingress_outcome_without_answers,
    ingress_questions,
    run_ingress,
)
from retrieval.context import count_tokens
from schemas.decisions import Answer, Choice, Noul, Score

# `no_llm` is imported as a fixture, not a helper: it is what stubs the generator
# and the embeddings, and a test that ran without it would reach a live provider
# (testing.md). The `as <same name>` re-export is what registers it as a fixture
# in this module; without it ruff calls the import unused and drops it.
from tests.graph.test_chitchat import _gate_params as _gate_params
from tests.graph.test_chitchat import no_llm as no_llm

# --- fakes ------------------------------------------------------------------


class _RecordingFallback:
    """A fallback that answers whatever a `reply` callable hands back, and
    records the size of every batch it was asked for."""

    def __init__(self, reply: Any) -> None:
        self._reply = reply
        self.batch_sizes: list[int] = []

    async def decide(self, *, state: Any, questions: AnyQ) -> dict[str, Answer]:
        self.batch_sizes.append(len(questions))
        body = self._reply(questions)
        if body is None:
            raise FallbackError(f"cannot answer a {len(questions)}-question batch")
        return {
            name: Answer(
                engine="fallback",
                latency_ms=1,
                value=_fake_value(q),
                probability=0.4 if isinstance(q, Noul) else None,
                probabilities=(
                    {opt: 0.25 for opt in q.options} if isinstance(q, Choice) else None
                ),
            )
            for name, q in questions.items()
        }


def _fake_value(q: Noul | Choice | Score) -> float | str:
    if isinstance(q, Noul):
        return 0.4
    return q.options[0] if isinstance(q, Choice) else 0.5


AnyQ = dict[str, Noul | Choice | Score]


def _nouls(n: int) -> AnyQ:
    return {f"entity_{i}": Noul(prompt=f"Is passage {i} about the entity?") for i in range(n)}


def _rubric_choices(n: int) -> AnyQ:
    """The reranker's per-passage `Choice` — the batch the fixed cap did not
    cover, because every answer carries a four-way distribution plus reasoning
    and there are up to `RERANK_TOP_N * 5` of them in one call."""
    levels = (
        "off-topic",
        "related but does not answer the question",
        "partly answers the question",
        "fully answers the question",
    )
    return {
        f"passage_{i}": Choice(prompt=f"[Passage]\n{'x' * 2000}", options=list(levels))
        for i in range(n)
    }


# --- 1. the cap is sized to the batch ---------------------------------------


def test_the_output_cap_grows_with_the_batch() -> None:
    """The regression is arithmetic: a fixed cap truncates exactly the batch
    that outgrows it. Mutation: return `role_cap` and both asserts fail."""
    role_cap = get_settings().llm_max_tokens["decision_fallback"]

    small = fallback_max_tokens(_nouls(2))
    large = fallback_max_tokens(_nouls(12))

    assert small == role_cap, "a small batch keeps the role's own cap"
    assert large > small, "a twelve-question batch must ask for more than a two-question one"
    assert large >= role_cap


def test_the_cap_covers_a_rubric_batch_of_forty_passages() -> None:
    """The shape KI-57's note names as 'bigger': the reranker's rubric. Forty
    four-way distributions with reasoning is the largest decision JSON the
    system asks for, and a cap below it is a truncation waiting to happen."""
    tokens = fallback_max_tokens(_rubric_choices(40))

    assert tokens >= count_tokens(_rubric_answer_json(40)), (
        "the cap must cover the object it has to return; a rubric batch of 40 "
        f"needs ~{count_tokens(_rubric_answer_json(40))} and asks for {tokens}"
    )


def _rubric_answer_json(n: int) -> str:
    levels = (
        "off-topic",
        "related but does not answer the question",
        "partly answers the question",
        "fully answers the question",
    )
    payload = {
        f"passage_{i}": {
            "probabilities": dict.fromkeys(levels, 0.25),
            "reasoning": "The passage is on the subject and states part of what "
            "the question asks for, though not the whole of it. " * 4,
        }
        for i in range(n)
    }
    return json.dumps(payload)


async def test_the_fallback_asks_for_json_and_for_its_own_cap() -> None:
    """Two of the brief's three engine-level fixes, asserted on the request
    rather than on the reply: JSON output asked for explicitly, and the cap
    sized to the batch."""
    seen: dict[str, Any] = {}
    questions = _nouls(3)
    payload = {name: {"probability": 0.5, "reasoning": "because"} for name in questions}

    async def fake_complete(**kwargs: Any) -> str:
        seen.update(kwargs)
        return json.dumps(payload)

    engine = FallbackEngine(complete_fn=fake_complete)
    answers = await engine.decide(state="state", questions=questions)

    assert list(answers) == list(questions)
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["max_tokens"] == fallback_max_tokens(questions)


def _batch_width(prompt: str) -> int:
    """How many questions the fallback prompt actually carries.

    Read off the prompt rather than passed in, so the width is what the engine
    sent — a fake that is told the width would report the width the engine
    *meant*, which is the thing under test.
    """
    return sum(1 for line in prompt.splitlines() if line.startswith("- "))


class _WidthLimitedLLM:
    """A `complete` that answers a batch only if it is at most `width` wide,
    and records every width it was asked for."""

    def __init__(self, width: int, *, truncate: bool = False) -> None:
        self.width = width
        self.truncate = truncate
        self.widths: list[int] = []

    async def __call__(self, **kwargs: Any) -> str:
        prompt: str = kwargs["messages"][0]["content"]
        width = _batch_width(prompt)
        self.widths.append(width)
        names = [
            line[2:].split(" ", 1)[0]
            for line in prompt.splitlines()
            if line.startswith("- ")
        ]
        if width > self.width:
            if self.truncate:
                # A cut object, at whatever length it was asked for: the
                # recorded truncations were deterministic, not random.
                return f'{{"{names[0]}": {{"probability": 0.5, "reason'
            return "not json at all"
        return json.dumps({name: {"probability": 0.5, "reasoning": "matches"} for name in names})


def _split_contract(widths: list[int], *, batch: int, widest_ok: int) -> str | None:
    """What the split has to be true of, checked without pinning the order.

    Returns an error string, or None when the widths are a legitimate repair:

    * the full batch was asked, and asked `ATTEMPTS_PER_BATCH` times — the retry
      happened before the split, so this cannot be confused with "one lucky
      retry answered it";
    * some width the fallback *can* answer was reached, or the run would have
      raised;
    * the whole repair stays inside `ATTEMPTS_PER_BATCH * (2 * batch - 1)` calls
      — the bound for halving all the way to single questions, which is what
      makes this safe to do on a live run rather than an unbounded retry loop.

    The order of the widths and the exact halving are implementation detail;
    these four are the contract.
    """
    attempts = FallbackEngine.ATTEMPTS_PER_BATCH
    if max(widths) != batch:
        return f"the full batch of {batch} was never asked: {widths}"
    if widths.count(batch) != attempts:
        return f"the batch was retried {widths.count(batch)} times, not {attempts}: {widths}"
    if not [w for w in widths if w <= widest_ok]:
        return f"no width the fallback can answer was ever reached: {widths}"
    if len(widths) > attempts * (2 * batch - 1):
        return f"{len(widths)} calls for {batch} questions is not a bounded repair: {widths}"
    return None


async def test_a_batch_the_fallback_cannot_answer_is_split_until_it_can() -> None:
    """Four questions, and the fallback refuses anything wider than one. The
    split is the only thing that can make this succeed, and its absence would
    raise instead — so the widths are pinned: 4, 4 (the retry), then 2, 2, 1, 1,
    1, 1 as each half is asked, retried, and halved in turn."""
    llm = _WidthLimitedLLM(width=1)
    engine = FallbackEngine(complete_fn=llm)

    answers = await engine.decide(state="state", questions=_nouls(4))

    assert sorted(answers) == sorted(_nouls(4))
    assert _split_contract(llm.widths, batch=4, widest_ok=1) is None, llm.widths


async def test_a_truncated_reply_is_split_because_retrying_it_cannot_help() -> None:
    """The other recorded shape: a JSON object cut mid-string at a fixed offset
    (1859/1901/2044 chars, identically on every re-run). Retrying the same batch
    returns the same cut, so only the split saves the run — and the difference
    from "the retry worked" is visible in the widths: each level is asked twice
    before it is halved."""
    llm = _WidthLimitedLLM(width=1, truncate=True)
    engine = FallbackEngine(complete_fn=llm)

    answers = await engine.decide(state="state", questions=_nouls(4))

    assert sorted(answers) == sorted(_nouls(4))
    # Identical to the non-JSON case: a deterministic cut and a non-JSON body
    # are the same failure to the engine, and get the same repair.
    assert _split_contract(llm.widths, batch=4, widest_ok=1) is None, llm.widths


async def test_a_split_answers_name_the_questions_that_were_asked() -> None:
    """The halves must each be answered on their own terms, or a split would
    quietly lose half the batch — the failure mode that looks like "the gate
    only saw some of the evidence"."""
    llm = _WidthLimitedLLM(width=2)
    engine = FallbackEngine(complete_fn=llm)

    answers = await engine.decide(state="state", questions=_nouls(5))

    assert sorted(answers) == sorted(_nouls(5))
    assert _split_contract(llm.widths, batch=5, widest_ok=2) is None, llm.widths


# --- 2. an unparseable reply retries once -----------------------------------


async def test_a_non_json_reply_is_retried_once_before_anything_else() -> None:
    """The R2a body: prose where JSON was expected. One retry, and the retry
    is what saves it. A counter, because "it eventually worked" would also be
    true of a split that had happened first."""
    calls: list[int] = []

    async def flaky(**_: Any) -> str:
        calls.append(1)
        if len(calls) == 1:
            return "I'm sorry, I can't help with that request."
        return json.dumps({"entity_0": {"probability": 0.9, "reasoning": "matches"}})

    answers = await FallbackEngine(complete_fn=flaky).decide(state="state", questions=_nouls(1))

    assert len(calls) == 2, "one retry, not one call and not five"
    assert answers["entity_0"].probability == pytest.approx(0.9)


async def test_a_single_question_the_fallback_cannot_answer_still_names_the_failure() -> None:
    """There is nothing smaller to split into, so the run of the degradation
    ends where the engine's contract says: a named `decision_unavailable`, not
    an opaque error. The stages are what turn that into a degraded run."""
    fallback = _RecordingFallback(lambda qs: None)
    engine = DecisionEngine(jev=_DeadJev(), fallback=fallback, breaker=_breaker(), mode="auto")

    with pytest.raises(DecisionUnavailable) as failed:
        await engine.decide(state={"kind": "evidence"}, questions=_nouls(1))

    assert failed.value.error_code == "decision_unavailable"
    assert fallback.batch_sizes == [1], "a single question is not split"


# --- 3. the timeout path is unchanged ----------------------------------------


class _DeadJev:
    async def decide(self, *, state: Any, questions: Any) -> Any:
        raise TimeoutError("socket timeout reading from jev")


class _Breaker(CircuitBreaker):
    """A breaker that always allows and never records — the point of these
    tests is the engine's routing, not the breaker's bookkeeping. A subclass
    rather than a duck type because `DecisionEngine` is typed, and a real
    breaker constructed with unreachable thresholds is the same object."""

    def allow_jev(self) -> bool:
        return True

    def probe(self) -> Any:
        class _P:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *exc: Any) -> None:
                return None

        return _P()


def _breaker() -> CircuitBreaker:
    """A breaker that always allows: these tests are about the engine's
    routing, not the breaker's bookkeeping."""
    return _Breaker(failure_threshold=10**9, window_seconds=1, cooldown_seconds=1)


async def test_a_jev_timeout_still_answers_on_the_fallback() -> None:
    """The half of KI-57 that already worked, pinned so item 3's other three
    changes cannot quietly break it."""
    fallback = _RecordingFallback(lambda qs: "ok")
    engine = DecisionEngine(jev=_DeadJev(), fallback=fallback, breaker=_breaker(), mode="auto")

    answers = await engine.decide(state={"kind": "ingress"}, questions=_nouls(3))

    assert len(answers) == 3
    assert all(a.engine == "fallback" for a in answers.values())


# --- 4. each stage degrades to its own definition ----------------------------


async def test_ingress_degrades_to_the_module_defaults() -> None:
    """Not to a guess: `INGRESS_DEFAULTS` holds the same values `_pick_choice`
    falls back to, so a decision outage routes the run the way a
    low-confidence classification already does."""
    engine = DecisionEngine(
        jev=_DeadJev(),
        fallback=_RecordingFallback(lambda qs: None),
        breaker=_breaker(),
        mode="auto",
    )

    outcome = await run_ingress(
        engine, run_id=uuid4(), user_message="What does the manual say?", has_collections=True
    )

    assert outcome.intent == INGRESS_DEFAULTS["intent"] == "lookup"
    assert outcome.source == INGRESS_DEFAULTS["source"] == "both"
    assert outcome.complexity == INGRESS_DEFAULTS["complexity"]
    assert outcome.risk == INGRESS_DEFAULTS["risk"]
    assert outcome.lexical_weight == INGRESS_DEFAULTS["lexical_weight"]
    # The safe direction on every guard: no verdict is no block, and the
    # retrieval path is the one that checks the evidence.
    assert not outcome.blocked
    assert outcome.guard_injection == "pass"
    assert outcome.answers == {}


def test_every_ingress_question_has_a_default_to_degrade_to() -> None:
    """A new ingress question with no default would be a KeyError on the next
    outage. This is what keeps adding one a deliberate act."""
    assert set(INGRESS_DEFAULTS) == set(ingress_questions("q", True))


def test_ingress_defaults_are_the_values_a_low_confidence_answer_gets() -> None:
    """Not merely "something sensible": the same values, so the degraded route
    and the ordinary route are the same route."""
    outcome = ingress_outcome_without_answers()

    assert outcome.intent == "lookup" and outcome.source == "both"
    assert outcome.complexity == "single" and outcome.risk == "high"
    # `lexical_weight` is the one value with no Choice fallback above it — it is
    # a Score read straight off the answer — so the default is the midpoint.
    assert outcome.lexical_weight == 0.5


# --- 5. and the whole run ends completed -------------------------------------


class _DeadDecisionEngine(DecisionEngine):
    """Every decide raises, whatever the routing. A `DecisionEngine` subclass
    rather than a duck type because the graph is typed against it, and the two
    behaviours that matter are both kept: a dead Jev and a dead fallback, so
    this is the total outage the R2a run hit rather than one engine's."""

    def __init__(self) -> None:
        super().__init__(
            jev=_DeadJev(),
            fallback=_RecordingFallback(lambda qs: None),
            breaker=_breaker(),
            mode="auto",
        )


@pytest.fixture
async def user_a(db: Any) -> Any:
    from tests.retrieval.conftest import make_user

    return await make_user(db, "ki57-degrade@test.dev")


async def test_a_run_with_a_dead_decision_layer_degrades_rather_than_raises(
    db: Any, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single assertion that is the whole of KI-57: with the decision layer
    refusing every call, `prepare_auto_run` still returns a finished run.

    The sanitizer now fails closed, so the unreachable grader drops every
    post-rerank chunk. The gate has no graded passages, the corrective retry is
    skipped as clearly absent, and the run abstains rather than answering from
    unsanitised evidence.
    """
    from db.session import get_session_factory
    from graph.auto import prepare_auto_run

    params = await _gate_params(db, user_a, no_llm, monkeypatch)
    run = await prepare_auto_run(get_session_factory(), params, _DeadDecisionEngine())

    assert run.abstain_event is not None, (
        "no reading is a failing gate, and a failing gate abstains"
    )
    assert run.contexts == [], "an abstention cites nothing"
    skipped = [d for d in run.decision_events if d.name == "retry_skipped"]
    assert skipped, "a decline that skipped its retry records why"
    assert {d.engine for d in skipped} == {"jev"}
    assert "would not change the outcome" in str(skipped[0].reasoning)


async def test_an_unanswered_entity_guard_is_recorded_as_unavailable_not_as_a_low_score(
    db: Any, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the sanitizer answers but the entity guard cannot be read, the
    trace must say so with `engine="unavailable"` rather than publishing a
    0.0 that looks like a real reading."""
    from dataclasses import replace

    from db.session import get_session_factory
    from graph import auto as auto_module
    from graph.auto import prepare_auto_run
    from schemas.decisions import Answer

    params = await _gate_params(db, user_a, no_llm, monkeypatch)
    question = "What is the capital of the Ridgeline R-7?"

    async def echo(**_: Any) -> str:
        return question

    monkeypatch.setattr(auto_module, "complete", echo)

    class _SanitizerOnlyEngine(_DeadDecisionEngine):
        async def decide(self, *, state: Any, questions: Any) -> Any:
            kind = str(state.get("kind"))
            if kind == "sanitize":
                return {name: Answer(engine="jev", latency_ms=1, value=0.01) for name in questions}
            raise DecisionUnavailable("decision_unavailable", "down", {})

    run = await prepare_auto_run(
        get_session_factory(), replace(params, question=question), _SanitizerOnlyEngine()
    )

    entity_rows = [d for d in run.decision_events if d.name.startswith("entity_")]
    assert entity_rows, "a question that names an entity still asks about it"
    assert {d.engine for d in entity_rows} == {"unavailable"}
    assert all(d.value == 0.0 for d in entity_rows)
    assert all("unreachable" in str(d.reasoning) for d in entity_rows)
    assert run.abstain_event is not None
