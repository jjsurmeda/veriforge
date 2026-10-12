"""KI-31: one unresolved generation id must not discard the whole item.

The recorded shape (docs/known-issues.md, KI-31, evidence from D3 run 3): four
items each carried a real `provider_ms` of 3481 / 6202 / 3622 / 3472 ms and a
null `our_overhead_ms`, because `Attribution.complete` required
`unattributed == 0` — so ONE id that never came back threw away the provider
time that *did* resolve, and the item's wall clock counted as nobody's.

The brief's requirement for phase 1d item 3b is that partial attribution keeps
what resolved and counts coverage per id, rather than discarding the figure.
That behaviour exists; this file pins it, including the direction of the
remaining gap, because the gated median must not be a guess.

No database and no provider: the lookups are stubbed.
"""

from collections.abc import Callable
from typing import Any

import pytest

from evals.attribution import (
    STATS_ATTEMPTS,
    Attribution,
    GenerationRef,
    Unresolved,
    _attribute_ids,
    attribute,
)


def _ref(generation_id: str) -> GenerationRef:
    return GenerationRef(generation_id=generation_id, source="litellm", role="generator")


StatsAnswers = Callable[[dict[str, float | None]], dict[str, int]]


@pytest.fixture
def stats_answers(monkeypatch: pytest.MonkeyPatch) -> StatsAnswers:
    """Stub the OpenRouter stats lookup. `answers[id]` is the `generation_time`
    the record would carry, or None to mean "never landed"."""

    def _install(answers: dict[str, float | None]) -> dict[str, int]:
        calls: dict[str, int] = {}

        async def fake_stats(generation_id: str) -> tuple[dict[str, Any] | None, int | None, int]:
            calls[generation_id] = calls.get(generation_id, 0) + 1
            ms = answers.get(generation_id)
            if ms is None:
                # Exhaust the budget without sleeping between attempts.
                return None, 404, STATS_ATTEMPTS
            return {"generation_time": ms}, 200, 1

        monkeypatch.setattr("evals.attribution._stats", fake_stats)
        return calls

    return _install


class TestPartialAttributionKeepsWhatResolved:
    @pytest.mark.asyncio
    async def test_one_unresolved_id_keeps_the_other_ids_provider_time(
        self, stats_answers: StatsAnswers
    ) -> None:
        """KI-31's recorded shape: 3 ids resolve, 1 does not. The resolved
        provider time is kept rather than discarded with the unresolved one."""
        stats_answers({"gen-a": 1000.0, "gen-b": 2000.0, "gen-c": 3000.0})
        provider_ms, attributed, unresolved = await _attribute_ids(
            [_ref("gen-a"), _ref("gen-b"), _ref("gen-c"), _ref("gen-d")]
        )
        assert provider_ms == 6000
        assert attributed == 3
        assert [entry.generation_id for entry in unresolved] == ["gen-d"]

    @pytest.mark.asyncio
    async def test_coverage_is_counted_per_id(self, stats_answers: StatsAnswers) -> None:
        """Coverage is per id, not a single flag: three of four resolved is
        3/4, and the count of what did NOT is reported alongside it."""
        stats_answers({"gen-a": 1000.0, "gen-b": 2000.0, "gen-c": 3000.0})
        result = await attribute(
            11_545.0, [_ref("gen-a"), _ref("gen-b"), _ref("gen-c"), _ref("gen-d")]
        )
        assert result.provider_ms == 6000
        assert result.attributed == 3
        assert result.unattributed == 1
        assert result.partial is True

    @pytest.mark.asyncio
    async def test_a_fully_resolved_item_is_complete(self, stats_answers: StatsAnswers) -> None:
        stats_answers({"gen-a": 1000.0, "gen-b": 2000.0})
        result = await attribute(5000.0, [_ref("gen-a"), _ref("gen-b")])
        assert result.complete is True
        assert result.partial is False
        # And the gated figure is the remainder.
        assert result.overhead_ms == 5000 - 3000

    @pytest.mark.asyncio
    async def test_no_ids_at_all_is_neither_complete_nor_partial(self) -> None:
        """An item with nothing to attribute records no overhead rather than
        claiming the whole wall clock as ours."""
        result = await attribute(5000.0, [])
        assert result.attributed == 0
        assert result.complete is False
        assert result.partial is False


class TestTheGatedFigureIsWithheldOnAPartialItem:
    """The direction the brief cares about, and the one KI-31's own note
    insists on: `our_overhead_ms` is still withheld when an id is unresolved,
    because a partial provider sum UNDERSTATES provider time and would
    OVERSTATE our overhead — flattering the number the gate hard-limits.

    What changed for KI-31 is that the provider time that DID resolve is kept
    and reported, and the gap is visible, rather than the whole item's figure
    being thrown away silently.
    """

    @pytest.mark.asyncio
    async def test_a_partial_sum_does_not_produce_a_gated_overhead(
        self, stats_answers: StatsAnswers
    ) -> None:
        stats_answers({"gen-a": 1000.0})
        result = await attribute(11_545.0, [_ref("gen-a"), _ref("gen-d")])
        # The naive remainder would be 11545 - 1000 = 10545, which charges the
        # unresolved generation's time to us.
        assert result.overhead_ms == 10_545
        # Which is exactly why `complete` is what the gate keys on.
        assert result.complete is False

    def test_the_gate_keys_on_complete_not_on_a_remainder(self) -> None:
        """The runner only writes `our_overhead_ms` for a complete item, so a
        partial one is reported through `generations_unattributed` instead."""
        import inspect

        from evals import runner

        source = inspect.getsource(runner.run_eval)
        assert "if attribution.complete:" in source
        assert 'stage_ms["our_overhead_ms"]' in source


class TestUnresolvedIdsAreDiagnosable:
    def test_an_unresolved_id_names_its_call_site(self) -> None:
        entry = Unresolved(
            ref=GenerationRef(
                generation_id="gen-x",
                source="litellm",
                model="openai/gpt-4o-mini",
                role="generator",
                job="generate",
            ),
            last_status=404,
            attempts=STATS_ATTEMPTS,
            api_type=None,
        )
        described = entry.describe()
        assert "gen-x" in described
        assert "gpt-4o-mini" in described
        assert "role=generator" in described
        assert "job=generate" in described
        assert "404" in described

    def test_a_transport_failure_is_its_own_class(self) -> None:
        """KI-31 could not tell "404 forever" from "the request never got an
        answer"; `last_status=None` is that difference."""
        entry = Unresolved(
            ref=GenerationRef(generation_id="gen-y", source="jev"),
            last_status=None,
            attempts=STATS_ATTEMPTS,
            api_type=None,
        )
        assert "transport-error" in entry.describe()

    @pytest.mark.asyncio
    async def test_a_record_with_no_duration_is_reported_separately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A record that lands but carries no `generation_time`/`latency` used to
        look identical to a 404; it is now its own class with `api_type`."""

        async def fake_stats(generation_id: str) -> tuple[dict[str, Any] | None, int | None, int]:
            return {"api_type": "decisions"}, 200, 1

        monkeypatch.setattr("evals.attribution._stats", fake_stats)
        _provider_ms, attributed, unresolved = await _attribute_ids([_ref("gen-z")])
        assert attributed == 0
        assert len(unresolved) == 1
        assert unresolved[0].last_status == 200
        assert unresolved[0].api_type == "decisions"


class TestNoFigureIsInvented:
    @pytest.mark.asyncio
    async def test_an_item_where_nothing_resolved_gets_no_provider_time(
        self, stats_answers: StatsAnswers
    ) -> None:
        """The rule from KI-18, which KI-31 must not erode: a miss contributes
        zero, never a guess."""
        stats_answers({})
        provider_ms, attributed, unresolved = await _attribute_ids(
            [_ref("gen-a"), _ref("gen-b")]
        )
        assert provider_ms == 0
        assert attributed == 0
        assert len(unresolved) == 2


def test_attribution_defaults_to_no_unresolved_list() -> None:
    """`complete` is a property, not a stored flag, so it cannot drift from
    the counts it is computed from."""
    result = Attribution(total_ms=1000.0, provider_ms=1000, attributed=1, unattributed=0)
    assert result.complete is True
    assert result.unresolved == []