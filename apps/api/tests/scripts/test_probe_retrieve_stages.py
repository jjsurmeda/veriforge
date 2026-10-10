"""The item-0 probe's measurement core, tested with fakes (no live stack).

`attribute` turns one run's SSE events into per-stage spans and `summarise`
turns many runs into the table the lane is ordered by. Both are pure functions
of the event list, so the table can be checked here rather than only on a live
run — which is the whole point: a probe that is wrong in the same way on every
run is worse than no probe.

The properties worth testing are the ones a reader of the table relies on:

* a step's span is the gap between its own started and completed events, so a
  step nested inside `retrieve` does not double-count against it;
* the per-variant searches sum into one row;
* what the outer `retrieve` step contains that no sub-step published is
  reported on its own row, NOT folded into the searches — that residual is the
  thing items 1 and 3 change, so hiding it would hide the target;
* an unknown label keeps its own row instead of vanishing.
"""

from datetime import UTC, datetime, timedelta

from scripts.probe_retrieve_stages import (
    RunTimings,
    attribute,
    render,
    stage_for_label,
    summarise,
)

BASE = datetime(2026, 10, 7, 9, 0, 0, tzinfo=UTC)


def _event(kind: str, offset_ms: float, **extra: object) -> dict[str, object]:
    event: dict[str, object] = {
        "type": kind,
        "ts": (BASE + timedelta(milliseconds=offset_ms)).isoformat(),
    }
    event.update(extra)
    return event


def _step(label: str, start_ms: float, end_ms: float) -> list[dict[str, object]]:
    return [
        _event("step.started", start_ms, label=label, node="auto"),
        _event(
            "step.completed", end_ms, label=label, node="auto", duration_ms=int(end_ms - start_ms)
        ),
    ]


def test_a_step_span_is_its_own_gap_not_the_outer_steps() -> None:
    events = [
        *_step("ingress+rewrite", 0, 1200),
        *_step("retrieve", 1200, 5900),
        *_step("retrieve: the question", 1400, 3000),
        *_step("rerank", 5900, 6300),
        _event("run.completed", 7000),
    ]

    timings = attribute(events)

    assert timings.spans["retrieve"] == 4700
    assert timings.spans["hybrid searches (all variants)"] == 1600
    assert timings.spans["rerank"] == 400
    assert timings.spans["ingress+rewrite"] == 1200
    assert timings.total_ms == 7000
    assert timings.status == "run.completed"


def test_the_retrieve_residual_is_its_own_row_not_folded_into_the_searches() -> None:
    """The variants LLM call and the embeddings are inside the outer `retrieve`
    step and publish no sub-step of their own yet; hiding them in the search row
    would make items 1 and 3 look done before they are."""
    events = [
        *_step("retrieve", 0, 5000),
        *_step("retrieve: variant one", 500, 2000),
        *_step("retrieve: variant two", 2000, 3600),
        _event("run.completed", 6000),
    ]

    stats = {stat.stage: stat for stat in summarise([attribute(events)])}

    assert stats["retrieve"].p50_ms == 5000
    assert stats["hybrid searches (all variants)"].p50_ms == 3100
    assert stats["retrieve (unlabelled)"].p50_ms == 1900


def test_several_variants_sum_into_one_search_row() -> None:
    events = [
        *_step("retrieve: a", 0, 1000),
        *_step("retrieve: b", 1000, 1800),
        *_step("retrieve: c", 1800, 3000),
        _event("run.completed", 3100),
    ]

    timings = attribute(events)

    assert timings.spans["hybrid searches (all variants)"] == 3000


def test_the_same_label_twice_in_one_run_sums_across_attempts() -> None:
    """The Auto retry loop re-enters `retrieve`; a run that retried must not
    report only its last attempt."""
    events = [
        *_step("retrieve", 0, 2000),
        *_step("sufficient", 2000, 2200),
        *_step("retrieve", 2200, 4800),
        *_step("sufficient", 4800, 5000),
        _event("run.completed", 5200),
    ]

    timings = attribute(events)

    assert timings.spans["retrieve"] == 4600
    assert timings.spans["sufficient"] == 400


def test_an_unknown_label_keeps_its_own_row() -> None:
    events = [*_step("expand context", 0, 300), _event("run.completed", 400)]

    assert stage_for_label("expand context") == "expand context"
    assert attribute(events).spans["expand context"] == 300


def test_the_table_reports_p50_worst_and_share_across_runs() -> None:
    fast = attribute(
        [*_step("retrieve", 0, 2000), _event("run.completed", 2000)], client_ttft_ms=1800
    )
    slow = attribute(
        [*_step("retrieve", 0, 6000), _event("run.completed", 6000)], client_ttft_ms=5200
    )

    stats = {stat.stage: stat for stat in summarise([fast, slow])}

    table = render(list(stats.values()))
    assert stats["retrieve"].p50_ms == 4000
    assert stats["retrieve"].worst_ms == 6000
    assert stats["retrieve"].share == 4000 / 4000
    assert stats["time to first token (client)"].p50_ms == 3500
    assert stats["TOTAL (first token -> run end)"].p50_ms == 4000
    assert "| retrieve | 4000 | 6000 | 100.0% |" in table
    assert "| stage | p50 ms | worst ms | share |" in table


def test_a_run_with_no_events_yields_no_table_rather_than_a_division_by_zero() -> None:
    assert summarise([RunTimings(total_ms=0.0, ttft_ms=None)]) == []


def test_client_ttft_is_kept_when_the_run_publishes_none() -> None:
    events = [*_step("retrieve", 0, 900), _event("run.completed", 1000)]

    timings = attribute(events, client_ttft_ms=640.0)

    assert timings.ttft_ms == 640.0
