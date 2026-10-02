"""A3: a Jev generation record's provider time is `latency`, not `generation_time`.

D2 2c probed two live Jev calls against `POST /api/v1/systemone` and read
back the stats records ~20 s later. Both came back with
`api_type == "decisions"`, `generation_time` **0**, and the real duration in
`latency` (241 and 242 ms; 277/20 and 1579/35 native tokens). So under the
shipped method -- which summed `generation_time` -- every Jev millisecond
(counted by rerank batches, sufficient, sanitize, conflict, ingress and review
verification) was charged to *our* overhead, in the one figure the gate
hard-limits. A3 records Jev's time from `latency`; TRD §15's latency paragraph
now says so.

These are pure-function tests on `_record_provider_ms`, plus one through
`provider_time_ms` to show the effect on the gated number.
"""

import pytest

from evals.attribution import Attribution, _record_provider_ms, provider_time_ms

# The record shape D2's probe returned.
JEV = {"api_type": "decisions", "generation_time": 0, "latency": 240}


def test_a_jev_record_counts_its_latency_as_provider_time() -> None:
    """The number A3 turns on: 240 ms of latency is 240 ms of provider time."""
    assert _record_provider_ms(JEV) == 240


def test_a_chat_completion_still_counts_generation_time() -> None:
    """A3 is scoped to Jev. An ordinary completion's field is unchanged, and
    its `latency` (the whole round trip) is not the generation duration."""
    completion = {"api_type": "chat", "generation_time": 1234, "latency": 2400}
    assert _record_provider_ms(completion) == 1234


def test_a_jev_record_without_latency_is_not_attributed() -> None:
    """No latency means no measurement, not zero. Reporting 0 would claim Jev
    took no time and put the whole call back onto our overhead — the defect
    A3 fixes, reintroduced through the other door."""
    assert _record_provider_ms({"api_type": "decisions", "generation_time": 0}) is None


def test_a_record_with_neither_field_is_not_attributed() -> None:
    assert _record_provider_ms({"api_type": "chat"}) is None


def test_a_record_with_no_api_type_falls_back_to_generation_time() -> None:
    """The discriminator is `api_type == "decisions"`, so a record without one
    is treated as an ordinary completion rather than silently dropped."""
    assert _record_provider_ms({"generation_time": 500}) == 500


async def test_provider_time_sums_jev_latency_across_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: three calls -- two Jev at 240 ms, one completion at 1234 ms
    -- attribute 1714 ms and count as three attributed generations."""
    records = {
        "gen-jev-1": dict(JEV),
        "gen-jev-2": dict(JEV),
        "gen-chat-1": {"api_type": "chat", "generation_time": 1234, "latency": 1400},
    }

    async def fake_stats(
        generation_id: str,
    ) -> tuple[dict[str, object] | None, int | None, int]:
        record = records.get(generation_id)
        return (dict(record) if record is not None else None), (200 if record else 404), 1

    monkeypatch.setattr("evals.attribution._stats", fake_stats)
    provider_ms, attributed = await provider_time_ms(list(records))
    assert provider_ms == 240 + 240 + 1234
    assert attributed == 3


async def test_jev_latency_moves_time_off_our_overhead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consequence the gate sees. A 5000 ms item whose only generation is
    one Jev call at 240 ms is 4760 ms of ours, not 5000 ms — and it is
    `complete`, so the figure is recorded rather than withheld."""

    async def fake_stats(
        generation_id: str,
    ) -> tuple[dict[str, object] | None, int | None, int]:
        return dict(JEV), 200, 1

    monkeypatch.setattr("evals.attribution._stats", fake_stats)
    provider_ms, attributed = await provider_time_ms(["gen-jev-1"])
    result = Attribution(
        total_ms=5000, provider_ms=provider_ms, attributed=attributed, unattributed=0
    )
    assert result.overhead_ms == 5000 - 240
    assert result.complete


async def test_a_jev_call_the_old_method_would_have_read_as_zero() -> None:
    """The regression this pins, stated as the old arithmetic: summing
    `generation_time` over this record attributes 0 ms of provider time, so
    the item's whole 5000 ms was charged to us."""
    generation_time = JEV["generation_time"]
    assert isinstance(generation_time, int)
    old = Attribution(total_ms=5000, provider_ms=generation_time, attributed=1, unattributed=0)
    assert old.overhead_ms == 5000
    # The same record under A3:
    assert _record_provider_ms(JEV) == 240
