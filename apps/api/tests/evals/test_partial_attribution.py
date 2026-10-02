"""Partial attribution is reported, not discarded (KI-31).

`attribution.py` records `our_overhead_ms` only when every generation id on an
item resolved, so one id that never came back threw away the item's whole
figure — including provider time that *did* resolve. Because the slow items are
the ones that fail to attribute, the gated `p50_our_overhead_ms` is a median
over a flattering subset: 16-18 of 20 items across D3's three runs, with the
excluded ones carrying 33706 ms of pipeline time.

Three things are pinned here:

- a synthetic item with one unresolved id keeps its resolved `provider_ms` and
  is counted as unattributed, rather than losing the figure;
- `our_overhead_ms` is still withheld on a partial item, because a partial sum
  understates provider time and would overstate our overhead — the gated number
  must not be a guess;
- the summary carries `p50_total_ms_unattributed_items`, so the size of the
  excluded subset is visible next to the median that excludes it.

No network, no database: `_stats` is stubbed, so these are arithmetic over a
synthetic item.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from db.ids import uuid7
from db.models import EvalItem, EvalResult
from evals import runner
from evals.attribution import (
    STATS_ATTEMPTS,
    STATS_BACKOFF_SECONDS,
    Attribution,
    GenerationRef,
    attribute,
)

# asyncio_mode = "auto" (pyproject.toml), so the async tests need no marker and
# the two pure-`aggregate` ones stay sync.

# The longest measured wait between a call returning and its stats record being
# readable, over four consecutive `complete()` calls polled every 5 s: 0.4 s,
# 0.4 s, 0.4 s, 123.6 s (D4 item 2).
MEASURED_WORST_CASE_LANDING_S = 123.6

JEV_RECORD = {"api_type": "decisions", "generation_time": 0, "latency": 240}
CHAT_RECORD = {"api_type": "chat", "generation_time": 1234}


def test_the_lookup_budget_covers_the_measured_landing_tail() -> None:
    """The KI-31 cause, pinned as arithmetic rather than as a comment.

    Measured 2026-10-02 over four consecutive calls: 0.4 s, 0.4 s, 0.4 s and
    **123.6 s** for the record to land. The budget was 8 x 3.0 s ~= 21 s, which
    is why ids 404'd for the whole budget and then answered 200 a minute later.
    A budget below the measured tail is the defect; this fails if the constants
    are ever lowered back under it.
    """
    budget_s = (STATS_ATTEMPTS - 1) * STATS_BACKOFF_SECONDS
    assert budget_s >= MEASURED_WORST_CASE_LANDING_S, (
        f"lookup budget {budget_s:.0f}s is below the measured {MEASURED_WORST_CASE_LANDING_S}s "
        "tail; ids will be reported unresolved that simply had not landed yet"
    )


def _stats_from(
    records: dict[str, dict[str, object]],
) -> Callable[[str], Awaitable[tuple[dict[str, object] | None, int | None, int]]]:
    """A `_stats` stub over a fixed id->record map; absent ids 404 forever."""

    async def fake_stats(
        generation_id: str,
    ) -> tuple[dict[str, object] | None, int | None, int]:
        record = records.get(generation_id)
        if record is None:
            return None, 404, STATS_ATTEMPTS
        return dict(record), 200, 1

    return fake_stats


async def test_a_synthetic_item_with_one_unresolved_id_keeps_its_resolved_provider_ms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case KI-31 describes: two calls, one resolves. The 240 ms that did
    resolve is real provider time and must not be thrown away with the miss."""
    monkeypatch.setattr(
        "evals.attribution._stats",
        _stats_from({"gen-jev-1": JEV_RECORD}),
    )
    refs = [
        GenerationRef(generation_id="gen-jev-1", source="jev", role="decision_engine"),
        GenerationRef(
            generation_id="gen-chat-1",
            source="litellm",
            model="openrouter/openai/gpt-4o-mini",
            role="generator",
            job="generate",
        ),
    ]
    result = await attribute(5000.0, refs)

    assert result.provider_ms == 240
    assert result.attributed == 1
    assert result.unattributed == 1
    assert result.partial
    assert not result.complete


async def test_an_unresolved_id_is_named_with_its_call_site_and_final_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The diagnosis KI-31 could not make: the id alone cannot say whether it
    was a Jev call, a dead stream or the reviewer's revision."""
    monkeypatch.setattr("evals.attribution._stats", _stats_from({"gen-jev-1": JEV_RECORD}))
    refs = [
        GenerationRef(generation_id="gen-jev-1", source="jev", role="decision_engine"),
        GenerationRef(
            generation_id="gen-chat-1",
            source="litellm",
            model="openrouter/openai/gpt-4o-mini",
            role="claim_extractor",
            job="review",
        ),
    ]
    result = await attribute(5000.0, refs)

    assert len(result.unresolved) == 1
    entry = result.unresolved[0]
    assert entry.generation_id == "gen-chat-1"
    assert entry.last_status == 404
    assert entry.attempts == STATS_ATTEMPTS
    assert entry.api_type is None  # no record came back at all
    described = entry.describe()
    assert "id=gen-chat-1" in described
    assert "role=claim_extractor" in described
    assert "job=review" in described
    assert "last_status=404" in described


async def test_a_record_without_a_duration_field_is_reported_as_its_own_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Different failure, same symptom: the record lands but carries no time,
    so it contributes nothing. `api_type` distinguishes it from a 404."""
    monkeypatch.setattr(
        "evals.attribution._stats",
        _stats_from({"gen-jev-1": JEV_RECORD, "gen-chat-1": {"api_type": "chat"}}),
    )
    result = await attribute(
        5000.0,
        [
            GenerationRef(generation_id="gen-jev-1", source="jev"),
            GenerationRef(generation_id="gen-chat-1", source="litellm", role="generator"),
        ],
    )
    (entry,) = result.unresolved
    assert entry.generation_id == "gen-chat-1"
    assert entry.api_type == "chat"
    assert entry.last_status == 200
    assert result.provider_ms == 240  # the resolved one is still counted


async def test_a_complete_item_is_unaffected() -> None:
    """No regression on the path that already worked: every id resolved, so the
    gated overhead is recorded as before."""
    result = Attribution(total_ms=5000, provider_ms=4200, attributed=3, unattributed=0)
    assert result.complete
    assert not result.partial
    assert result.overhead_ms == 800


def _item() -> EvalItem:
    return EvalItem(
        dataset_id=uuid7(),
        category="single_document_lookup",
        question="q",
        reference_answer="",
        should_abstain=False,
    )


def _result(latency_ms: int, stage_ms: dict[str, Any] | None) -> EvalResult:
    return EvalResult(
        eval_run_id=uuid7(),
        item_id=uuid7(),
        answer="ok",
        latency_ms=latency_ms,
        stage_ms=stage_ms,
    )


def test_the_summary_reports_the_excluded_items_wall_clock() -> None:
    """`p50_total_ms_unattributed_items` is the median wall clock of exactly the
    items whose overhead the median above excludes, so the bias has a number."""
    results: list[tuple[EvalItem, EvalResult]] = [
        (_item(), _result(5000, {"our_overhead_ms": 800})),
        (_item(), _result(6000, {"our_overhead_ms": 1200})),
        # The two slow items — real provider time, one id missing each — record
        # no overhead and so drop out of the gated median. Their wall clocks are
        # D3 run 3's measured values.
        (
            _item(),
            _result(
                11545,
                {"provider_ms": 3481, "generations_attributed": 3, "generations_unattributed": 1},
            ),
        ),
        (
            _item(),
            _result(
                10140,
                {"provider_ms": 6202, "generations_attributed": 5, "generations_unattributed": 1},
            ),
        ),
    ]

    summary = runner.aggregate(results)

    assert summary["p50_our_overhead_ms"] == 1000.0  # median of 800, 1200 only
    assert summary["overhead_items_attributed"] == 2.0
    assert summary["p50_total_ms_unattributed_items"] == 10842.5  # median of 11545, 10140
    # The point of the new field: the gated median is drawn from the fast half.
    excluded = summary["p50_total_ms_unattributed_items"]
    gated = summary["p50_our_overhead_ms"]
    assert excluded is not None and gated is not None
    assert float(excluded) > float(gated)


def test_the_new_field_is_null_when_every_item_attributed() -> None:
    """No coverage gap, no new row: the field reports a gap, not a number."""
    summary = runner.aggregate([(_item(), _result(5000, {"our_overhead_ms": 800}))])
    assert summary["p50_total_ms_unattributed_items"] is None
    assert summary["p50_our_overhead_ms"] == 800.0
