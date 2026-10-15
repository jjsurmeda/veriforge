"""The gate-calibration probe's record shape.

`scripts/calibrate_gate.py` is the measurement ADR-006 defers to: "calibrate on
the recorded acceptance and entity-mismatch items". A measurement that is only
run once and read once is worth very little — nobody can tell, a year later,
whether a row means what it says, or whether a column quietly changed
definition and the threshold it picked still refers to the same thing.

So this pins the **shape**, with fakes and no provider (testing.md):

* every row carries the four numbers a candidate gate could be built on, and
  each is a real 0-1 reading or explicitly `None` — never a 0.0 standing in for
  "not measured", which is the failure that makes a calibration table lie;
* `gated` is exactly "this class reaches the gate", so `smalltalk` and
  `library` can never be counted as abstentions and quietly flatter a
  threshold;
* the grades come off `kept_chunks`, the same set the gate judged, and the
  derived `top_grade` / `mean_top3` are the order statistics a cutoff on them
  would actually be applied to;
* an `unavailable` gate (KI-57) is recorded as `None`, not as 0.0 — the
  distinction between "judged thin" and "nobody could judge".

Nothing here runs a live model or reads a real corpus.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

from retrieval.hybrid import ScoredChunk
from schemas.events import Abstain, Decision
from scripts.calibrate_gate import (
    GATED_CLASSES,
    ProbeError,
    _corpus_ids,
    _grades,
    measure,
    write_report,
)


def _chunk(score: float) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=uuid4(),
        document_id=None,
        document_name="doc",
        section_id=None,
        ord=0,
        page=None,
        text="text",
        heading_path=None,
        source_type="document",
        vector_score=0.5,
        bm25_score=0.5,
        fused_score=0.5,
    ).with_rerank(score)


@dataclass
class _Ingress:
    intent: str = "lookup"


@dataclass
class _Run:
    """The parts of `AutoRun` the probe reads, and nothing else."""

    kept_chunks: list[ScoredChunk] = field(default_factory=list)
    decision_events: list[Decision] = field(default_factory=list)
    abstain_event: Abstain | None = None
    ingress: _Ingress = field(default_factory=_Ingress)
    rewritten: str = "the question"


def _decision(name: str, value: float, engine: str = "jev") -> Decision:
    return Decision(
        run_id="r",
        name=name,
        value=value,
        probability=value,
        probabilities=None,
        engine=engine,
        latency_ms=1,
    )


# --- the numbers a threshold is chosen on ------------------------------------


def _emitted(*decisions: Decision) -> list[Decision]:
    return list(decisions)


def test_the_row_carries_all_four_numbers_a_gate_could_be_built_on() -> None:
    """The brief's record: the expected class, the top rubric grade, the mean of
    the top 3, and `sufficient`. A column that is missing cannot be calibrated
    against, and the whole point of running the probe is to have all of them."""
    run = _Run(
        kept_chunks=[_chunk(0.90), _chunk(0.70), _chunk(0.50), _chunk(0.10)],
        decision_events=[
            _decision("sufficient", 0.61),
            _decision("entity_0_0", 0.93),
            _decision("entity_1_0", 0.12),
        ],
    )

    row = measure(run, "item-1", "answer", "lookup", 1, [])

    assert row["top_grade"] == pytest.approx(0.90)
    assert row["mean_top3"] == pytest.approx(statistics.fmean([0.90, 0.70, 0.50]))
    assert row["sufficient"] == pytest.approx(0.61)
    assert row["entity_max"] == pytest.approx(0.93)
    assert row["expect"] == "answer"


def test_the_grades_are_the_top_k_the_gate_itself_judged() -> None:
    """`kept_chunks` is the post-sanitize set that became the evidence. Reading
    the grades off anything else — the fused order, the pre-sanitize top 8 —
    would calibrate a gate against a set the gate never saw."""
    run = _Run(kept_chunks=[_chunk(s) for s in (0.1, 0.9, 0.4)])

    assert _grades(run) == [0.9, 0.4, 0.1], "best first, whatever order they arrived in"


def test_mean_top3_uses_the_top_three_and_not_more() -> None:
    """A mean over all eight winners is a different statistic and would move the
    cutoff; `mean_top3` has to mean what its name says."""
    run = _Run(kept_chunks=[_chunk(s) for s in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3)])

    row = measure(run, "item", "answer", "lookup", 1, [])

    assert row["n_passages"] == 8
    assert row["mean_top3"] == pytest.approx(statistics.fmean([1.0, 0.9, 0.8]))
    every = statistics.fmean([1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3])
    assert row["mean_top3"] != pytest.approx(every), (
        "a mean over all eight is a different statistic and would move the cutoff"
    )


def test_a_short_evidence_set_measures_the_mean_of_what_there_was() -> None:
    """Two passages is not an error; it is a mean of two. The alternative —
    refusing the row — would silently drop exactly the thin-evidence items the
    calibration most needs to see."""
    run = _Run(kept_chunks=[_chunk(0.8), _chunk(0.4)])

    row = measure(run, "item", "not_in_sources", "lookup", 1, [])

    assert row["mean_top3"] == pytest.approx(0.6)
    assert row["top_grade"] == pytest.approx(0.8)


def test_no_evidence_is_none_and_not_zero() -> None:
    """The distinction the whole table rests on. A 0.0 here reads as "the
    rubric graded every passage off-topic", which is a measurement; `None`
    reads as "there was nothing to grade", which is what happened."""
    run = _Run(kept_chunks=[], decision_events=[_decision("sufficient", 0.02)])
    row = measure(run, "x", "answer", "lookup", 1, [])

    assert row["top_grade"] is None
    assert row["mean_top3"] is None
    assert row["sufficient"] == pytest.approx(0.02)


def test_an_unavailable_gate_is_none_rather_than_zero() -> None:
    """KI-57's `unavailable` row carries `value=0.0`, and reading it as a
    reading would put a degraded run into the calibration table as though the
    rubric had graded it. It did not."""
    run = _Run(
        kept_chunks=[_chunk(0.7)],
        decision_events=[_decision("sufficient", 0.0, engine="unavailable")],
    )

    row = measure(run, "x", "answer", "lookup", 1, [])

    assert row["sufficient"] is None
    assert row["gate_engine"] == "unavailable", "the outage is still recorded, just not as a score"


def test_the_gate_engine_is_recorded_so_a_fallback_reading_is_visible() -> None:
    """`sufficient` thresholds are per engine (TRD §8), so a row measured on the
    LLM fallback is on a different scale from one measured on Jev. The row says
    which, rather than leaving it to be assumed."""
    run = _Run(decision_events=[_decision("sufficient", 0.40, engine="fallback")])

    assert measure(run, "x", "answer", "lookup", 1, [])["gate_engine"] == "fallback"


# --- the emitter capture (the empty-column trap) ------------------------------


def test_entity_readings_arrive_only_through_the_emitter() -> None:
    """The probe calls `prepare_auto_run` directly, and `graph/stages/run_auto.py`
    — not `prepare_auto_run` — is what binds `DecisionEngine.set_event_emitter`.
    So the run's own `decision_events` carry `sufficient` (the evidence stage
    appends it) and **nothing else**: every per-passage `entity_` reading would
    be missing.

    This is the trap the calibration nearly reported as a product finding. An
    all-empty entity column is indistinguishable from "the entity guard never
    fires", and that is a claim about the guard, not about the probe.

    So the probe merges the emitter's capture with the run's own events, and
    this pins that it does."""
    run = _Run(kept_chunks=[_chunk(0.8)], decision_events=[_decision("sufficient", 0.62)])

    without = measure(run, "x", "answer", "lookup", 1, [])
    assert without["entity_measured"] is False
    assert without["entity_max"] is None

    emitted = [
        _decision("entity_0_0", 0.93),
        _decision("entity_1_0", 0.07),
        _decision("entity_0_1", 0.88),
    ]
    with_emitter = measure(run, "x", "answer", "lookup", 1, emitted)

    assert with_emitter["entity_measured"] is True
    assert with_emitter["entity_max"] == pytest.approx(0.93)
    # The entity index is the SECOND one: `checks._entity_passage_questions`
    # names rows passage-major (`entity_<passage>_<entity>`).
    assert with_emitter["entity_entities"] == ["0", "1"]


def test_a_conflict_row_is_merged_in_without_becoming_an_entity_reading() -> None:
    """Both prefixes come off the same batched call and both arrive on the same
    emitter, so a prefix test has to be exact — `entity_` does not match
    `conflict_`, but a looser one would silently average the conflict verdicts
    into the entity guard's max."""
    run = _Run(decision_events=[_decision("sufficient", 0.62)])
    emitted = [_decision("conflict_0", 0.99), _decision("entity_0_0", 0.31)]

    row = measure(run, "x", "answer", "lookup", 1, emitted)

    assert row["entity_max"] == pytest.approx(0.31)
    assert "conflict_0" in row["trace_gate_rows"]


def test_the_emitted_sufficient_does_not_shadow_the_runs_own_verdict() -> None:
    """The run's own `sufficient` is the one that decided the verdict; the
    emitter's copy of the same name is the same reading. If both are merged,
    taking the last must not let a stale one win — and taking the first must not
    report the pre-correction attempt."""
    run = _Run(
        decision_events=[
            _decision("sufficient", 0.02),
            _decision("sufficient", 0.71),
        ]
    )
    emitted = [_decision("sufficient", 0.71)]

    row = measure(run, "x", "answer", "lookup", 1, emitted)

    assert row["sufficient"] == pytest.approx(0.71), (
        "the second attempt is the one the verdict came from"
    )


def test_the_record_says_which_query_the_grades_were_graded_against() -> None:
    """The gate reads the *rewritten* query, not the user's message, and the
    rewrite is a model call that varies. Without the rewritten text a table row
    cannot be re-derived, and a change to the rewriter would move every number
    in it with nothing in the record to show why."""
    run = _Run(decision_events=[_decision("sufficient", 0.6)])
    run.rewritten = "What did Mary Bostan do after leaving her husband?"

    row = measure(run, "x", "answer", "lookup", 1, [])

    assert row["rewritten"] == "What did Mary Bostan do after leaving her husband?"


# --- classes that never reach the gate ---------------------------------------


def test_only_the_gated_classes_are_flagged_gated() -> None:
    """`smalltalk` and `library` are answered before retrieval. Counting them as
    "declined" would flatter every threshold, because they can only ever be
    counted the right way."""
    assert {"answer", "not_in_sources"} == GATED_CLASSES
    assert measure(_Run(), "hi", "smalltalk", "chitchat", 1, [])["gated"] is False
    assert measure(_Run(), "lib", "library", "library", 1, [])["gated"] is False
    assert measure(_Run(), "q", "answer", "lookup", 1, [])["gated"] is True
    assert measure(_Run(), "q", "not_in_sources", "lookup", 1, [])["gated"] is True


def test_the_record_says_what_the_run_did_not_only_what_it_scored() -> None:
    """`abstained` and `turns` are what make the table checkable against a
    later acceptance run: a threshold read off a row whose run declined is a
    different claim from one read off a row whose run answered."""
    abstention = Abstain(run_id="r", found_summary="", missing_summary="not covered")
    declined = measure(_Run(abstain_event=abstention), "x", "not_in_sources", "lookup", 1, [])
    answered = measure(_Run(), "x", "answer", "lookup", 2, [])

    assert declined["abstained"] is True
    assert answered["abstained"] is False
    assert answered["turns"] == 2, "a follow-up item is measured on its last turn"


# --- the entity-mismatch scope -----------------------------------------------


def test_an_entity_mismatch_item_is_scoped_to_its_own_corpus() -> None:
    """KI-54: the mismatch IS the label. With both corpora in scope the run
    could retrieve the answer from the other one and the item would measure
    nothing."""
    state = {
        "corpus_collection_id": "01a13f80-76e3-7e21-a2d6-fc89bb2d9ae4",
        "counterfactual_collection_id": "01a13f80-fa0e-7af6-a70d-1912f9486f31",
    }

    assert _corpus_ids(state, "seed") == [UUID("01a13f80-76e3-7e21-a2d6-fc89bb2d9ae4")]
    assert _corpus_ids(state, "counterfactual") == [
        UUID("01a13f80-fa0e-7af6-a70d-1912f9486f31")
    ]


def test_an_unknown_or_unloaded_scope_is_an_error_not_an_empty_scope() -> None:
    """An empty scope retrieves nothing, and a run over nothing abstains — which
    would add twelve free abstentions to the calibration and flatter every
    threshold. Failing is the only honest outcome."""
    with pytest.raises(ProbeError):
        _corpus_ids({}, "seed")
    with pytest.raises(ProbeError):
        _corpus_ids({"corpus_collection_id": "01a13f80-76e3-7e21-a2d6-fc89bb2d9ae4"}, "nope")


# --- the persisted artefact --------------------------------------------------


def test_the_written_report_says_which_commit_and_how_many_were_gated(tmp_path: Any) -> None:
    """A calibration file named after nothing, or without the commit it measured,
    is a number a later reader cannot trust. `write_report` carries both."""
    import scripts.calibrate_gate as probe_module

    original = probe_module.OUT_DIR
    probe_module.OUT_DIR = tmp_path
    try:
        gated_run = _Run(decision_events=[_decision("sufficient", 0.8)])
        rows = [
            measure(gated_run, "a", "answer", "l", 1, []),
            measure(_Run(), "b", "not_in_sources", "l", 1, []),
            measure(_Run(), "c", "smalltalk", "chitchat", 1, []),
        ]
        path = write_report("books", rows)
    finally:
        probe_module.OUT_DIR = original

    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["dataset"] == "books"
    assert payload["commit"]
    assert payload["summary"]["gated"] == 2
    assert payload["summary"]["skipped_ungated"] == 1
    assert len(payload["rows"]) == 3, "the ungated rows are kept, just not counted"
