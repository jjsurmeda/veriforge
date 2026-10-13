""": the generator's time to first token is labelled, not a silence.

Lane B item 3 labelled every step inside `retrieve` and stopped one function
too early. `runner.py` published no `step.started` for the generator, so the
single longest wait a user actually sits through — the run's time to first
token — was the one stage with nothing at all on the stream while it ran.
Measured on `main` (`1857362`): `step.completed: conflict` at 6869 ms, first
`answer.delta` at 18778 ms, an 8145 ms silence with no event in it, in a run
whose every *named* step was under 1.9 s.

That is why ADR-003's "no trace gap over 2 s" read as NOT MET on lane B even
though lane B cut the largest named gap: the gap that was left was the one
with no label on it.

The fix is one `_step` around `auto_run.stream_answer()`. What these tests
pin is the gap check itself: a silence over 2 s is only acceptable when a
step was open across it, and after the change none is left unlabelled.

Delays are SIMULATED (the fake generator sleeps) so the test is about what
gets published, not about how fast this machine is — a test that only passes
when the provider is quick is not testing the cadence.

Gaps are measured in **arrival time at the client**, not from the events' own
`ts`. A publish that reaches the stream 2 s after it was stamped reads as
instant in its own payload, and the thing CH-5 asks about is the silence a
watching client actually experiences.
"""

from itertools import pairwise
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.chats.test_ttft import _run_auto_and_collect

# CH-5 / ADR-003 §2: the rule is asserted against this, not against the
# simulated generator delay below.
MAX_GAP_SECONDS = 2.0
# Comfortably past the limit on its own. With the generator taking this long
# before its first token, a run that publishes nothing for it leaves a
# silence the check below cannot excuse, and a run that labels it does not.
# Pick the delay under the limit and the missing label would hide behind it.
FIRST_TOKEN_SECONDS = 2.4

GENERATE = "generate"


def _is_step(kind: str, data: dict[str, Any], event: str, label: str = GENERATE) -> bool:
    return kind == event and data.get("label") == label


def _unlabelled_gaps(
    transcript: list[tuple[str, dict[str, Any]]],
    stamps: list[float],
    limit: float = MAX_GAP_SECONDS,
) -> list[tuple[str, float]]:
    """Every silent interval over `limit` that no step was open across.

    This is the check  asks for, and it is deliberately NOT "largest gap
    anywhere in the run": a run ends with the reviewer re-reading every claim,
    and a silence after the user already has their text is a different thing
    from a silence they are waiting through. What must not exist is a long
    silence during which nothing has claimed to be running.
    """
    assert len(transcript) == len(stamps), "one arrival stamp per event"
    offenders: list[tuple[str, float]] = []
    step_open = False
    timeline = list(zip(transcript, stamps, strict=True))
    for ((before_kind, before), before_at), ((after_kind, after), after_at) in pairwise(timeline):
        # `before` is folded in FIRST: a step that opens at `before` is what
        # makes the silence after it explicable, so it has to be open before
        # this interval is judged.
        if _is_step(before_kind, before, "step.started"):
            step_open = True
        elif _is_step(before_kind, before, "step.completed"):
            step_open = False

        gap = after_at - before_at
        if gap > limit and not step_open:
            offenders.append(
                (
                    f"{before.get('label', before_kind)} -> {after.get('label', after_kind)}",
                    gap,
                )
            )
    return offenders


async def _slow_run(
    client: AsyncClient, db: AsyncSession, monkeypatch: Any
) -> tuple[list[tuple[str, dict[str, Any]]], list[float]]:
    stamps: list[float] = []
    transcript, _run_id = await _run_auto_and_collect(
        client,
        db,
        monkeypatch,
        delay_before_first_token_s=FIRST_TOKEN_SECONDS,
        arrival_stamps=stamps,
    )
    return transcript, stamps


class TestGeneratorStep:
    async def test_the_generator_publishes_its_own_step(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: Any
    ) -> None:
        transcript, _ = await _slow_run(client, db, monkeypatch)

        assert [data for kind, data in transcript if _is_step(kind, data, "step.started")], (
            "the generator published no step.started, so the longest wait a "
            f"user waits through is still unlabelled: {[k for k, _ in transcript]}"
        )

    async def test_the_step_brackets_the_tokens_it_produced(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: Any
    ) -> None:
        """A step that opens after the tokens, or closes before them, is a
        label in the wrong place. The point is that the client can say what it
        is waiting for *while* it is waiting."""
        transcript, _ = await _slow_run(client, db, monkeypatch)
        # Indexed BY LABEL, not by event type: `retrieve` and `rerank` publish
        # steps too, so the first `step.started` in the run is neither of the
        # two this test is about.
        start = next(
            i for i, (kind, data) in enumerate(transcript) if _is_step(kind, data, "step.started")
        )
        first_delta = next(
            i for i, (kind, _data) in enumerate(transcript) if kind == "answer.delta"
        )
        completed = next(
            i for i, (kind, data) in enumerate(transcript) if _is_step(kind, data, "step.completed")
        )
        assert start < first_delta < completed, (
            "generate must open before the first token and close after it, but "
            f"opened at {start}, the first token at {first_delta} and closed "
            f"at {completed}"
        )

    async def test_the_step_is_timed_and_lands_in_the_run_metrics(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: Any
    ) -> None:
        """It has to be attributable, not decorative: the duration belongs in
        `latency_ms` beside every other step, and `generate` must still be the
        same number the metrics event reports — the step and the metric are
        one measurement, not two clocks that can disagree."""
        transcript, _ = await _slow_run(client, db, monkeypatch)

        completed = [data for kind, data in transcript if _is_step(kind, data, "step.completed")]
        assert completed, "the generate step never completed"
        duration = completed[0]["duration_ms"]
        assert duration >= FIRST_TOKEN_SECONDS * 1000, (
            f"generate step reported {duration}ms for a wait of {FIRST_TOKEN_SECONDS}s"
        )

        metrics = next(data for kind, data in transcript if kind == "metrics")
        assert metrics["latency_ms"][GENERATE] == duration, (
            "the step and the metric are the same measurement: "
            f"{metrics['latency_ms'][GENERATE]} vs {duration}"
        )

    async def test_no_gap_over_two_seconds_is_left_without_a_step_to_explain_it(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: Any
    ) -> None:
        """The trace gap check  asks for.

        Measured on `main` with this fixture: one silence of 2.40 s between
        `step.completed: conflict` and the first `answer.delta`, with no step
        open across it. That is the whole defect — the run was working, it just
        said nothing.
        """
        transcript, stamps = await _slow_run(client, db, monkeypatch)
        offenders = _unlabelled_gaps(transcript, stamps)
        assert offenders == [], (
            f"silent gaps over {MAX_GAP_SECONDS}s with no step running: {offenders}"
        )

    async def test_the_gap_check_still_catches_an_unlabelled_one(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: Any
    ) -> None:
        """Asserted both ways, so the check above cannot pass for the wrong
        reason: the same helper, with the generate step's events removed, must
        report the silence it was written to catch. A gap check that finds
        nothing because it computes nothing is worse than no check."""
        transcript, stamps = await _slow_run(client, db, monkeypatch)
        # The stamps are filtered in step with the events: the gap check pairs
        # each event with the time it reached the client, so dropping an event
        # without dropping its stamp would misalign the two.
        kept: list[tuple[tuple[str, dict[str, Any]], float]] = []
        for (kind, data), stamp in zip(transcript, stamps, strict=True):
            if kind in ("step.started", "step.completed") and data.get("label") == GENERATE:
                continue
            kept.append(((kind, data), stamp))
        assert len(kept) == len(transcript) - 2, "the generate pair was removed"
        offenders = _unlabelled_gaps([e for e, _ in kept], [s for _, s in kept])
        assert offenders, "the check reported nothing even with the label removed"
        worst = max(gap for _label, gap in offenders)
        assert worst >= FIRST_TOKEN_SECONDS - 0.5, (
            f"the worst silence was {worst:.2f}s, under the fixture's "
            f"{FIRST_TOKEN_SECONDS}s wait — the check is measuring something else"
        )


class TestTheSlowGeneratorFixtureItself:
    """If the fixture stopped being slow, every test above would pass for the
    wrong reason: there would be no silence left to explain."""

    async def test_the_client_really_does_wait_before_its_first_token(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: Any
    ) -> None:
        transcript, stamps = await _slow_run(client, db, monkeypatch)
        kinds = [kind for kind, _ in transcript]
        assert "answer.delta" in kinds, kinds

        first_delta = kinds.index("answer.delta")
        wait = stamps[first_delta] - stamps[0]
        assert wait >= FIRST_TOKEN_SECONDS - 0.5, (
            f"the client saw the first token {wait:.2f}s after the run started, "
            f"which is not a slow-generator fixture at {FIRST_TOKEN_SECONDS}s"
        )
