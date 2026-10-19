#!/usr/bin/env python3
"""Calibrate the evidence gate on the two sets that decide it (R2a-2 item 1).

ADR-006 as corrected says the gate is the reranker's answer-containment grade.
This script is the calibration behind that number: it measures the grade the run
actually had, and the entity guard beside it. The old `sufficient` Noul is gone
from the path, so it is no longer measured.

**What it runs, per item: ingress → rewrite → retrieve → rerank (the rubric)
→ sanitize → the evidence check. No generation, no review.** That is
`prepare_auto_run` and nothing after it, which is why it costs about what a
third of a full acceptance item costs: the generator and the reviewer are the
expensive half and the gate never sees either.

For each item it records the numbers a candidate gate could be built on:

| field | what it is |
| --- | --- |
| `top_grade` | the highest answer-containment grade over the post-sanitize winners |
| `mean_top3` | the mean of the top three grades: strong throughout, not just at one |
| `entity_max` | the max entity reading, when the question named an entity |

Two sets, because the gate has to hold on both and they fail differently. The
**books** set (57) carries 32 answerables and 21 should-declines in one
corpus, so it is where a threshold trades false abstentions against confident
wrong answers. The **entity-mismatch** set (12) is 12 should-declines with no
answerable at all, each naming an entity that is attested in the *other*
corpus — it is the set that decides whether the entity guard is load-bearing,
and it can only be answered wrongly, never abstained wrongly.

The entity guard is **not** applied to the recorded columns on purpose. The
brief asks for what each candidate gate alone would let through, and a gate
that looks good only because the guard catches what it misses is a gate whose
threshold was chosen against the wrong signal.

Writes `.data/evals/gate-calibration-<dataset>.json` and prints the table, so
the numbers in the R2a-2 report can be re-derived rather than believed.

    DATABASE_URL=... uv run python scripts/calibrate_gate.py --dataset books
    DATABASE_URL=... uv run python scripts/calibrate_gate.py --dataset entity_mismatch

Spends provider credit: one Jev call for ingress, one small-model rewrite, a
handful of embeddings, one rubric rerank and one batched gate per item. Check
the OpenRouter balance first (docs/conventions/agents.md, "Credit pre-flight").
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from chats.scope import resolve_scope
from config import get_settings
from db.models import Chat, Message, User
from db.session import get_session_factory
from decisions.engine import DecisionEngine
from evals.loader import EVAL_USER_EMAIL, STATE_FILE
from evals.runner import CONTEXT_WINDOW, SMALL_MODEL
from graph.auto import AutoRunInput, prepare_auto_run
from retrieval.filters import ClientFilters
from schemas.decisions import Answer
from schemas.events import Decision

ROOT = Path(__file__).resolve().parents[3]
BOOKS_SET = ROOT / "evals" / "acceptance" / "books.json"
ENTITY_SET = ROOT / "evals" / "entity_mismatch" / "items.json"
OUT_DIR = ROOT / ".data" / "evals"

#: The generator never runs in this probe, so no generator model is needed; the
#: small model is what the rewrite uses, and it is the same one the eval runner
#: and the acceptance stack both use, so the rewrite is the rewrite the product
#: makes.
GENERATOR_MODEL = "openrouter/openai/gpt-4o-mini"

#: Classes the probe knows how to score. `smalltalk` and `library` never reach
#: the gate — they are answered before retrieval — so they are recorded as
#: `skipped` rather than being counted as abstentions, which would quietly
#: flatter any threshold.
GATED_CLASSES = {"answer", "not_in_sources"}


class ProbeError(RuntimeError):
    """Something about the environment, not about an item's quality."""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ProbeError(f"missing {path}")
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


async def _eval_user_id(session: Any) -> UUID:
    user: User = (
        await session.execute(select(User).where(User.email == EVAL_USER_EMAIL))
    ).scalar_one()
    return user.id


def _corpus_ids(state: dict[str, Any], scope_corpus: str) -> list[UUID]:
    """The private collection one entity-mismatch item is scoped to (KI-54).

    Read from the loader's state file rather than resolved by name, for the
    reason `evals/runner.py` gives: `resolve_scope` still checks ownership in
    SQL, so a wrong id retrieves nothing rather than leaking, and the state
    file is what the loader actually created.
    """
    if scope_corpus == "seed":
        raw = state.get("corpus_collection_id")
    elif scope_corpus == "counterfactual":
        raw = state.get("counterfactual_collection_id")
    else:
        raise ProbeError(f"unknown scope_corpus {scope_corpus!r}")
    if not raw:
        raise ProbeError(
            f"the {scope_corpus} corpus is not loaded; run `uv run python -m evals.loader`"
        )
    return [UUID(raw)]


def _entity_event(name: str, answer: Answer, call: Any, run_id: UUID) -> Decision:
    """The probe's stand-in for the run bus's decision emitter.

    **Without this the entity columns are silently empty**, which is the trap
    this probe nearly fell into: `prepare_auto_run` records the gate row itself
    (the evidence stage appends it), but every *other* answer — every
    per-passage entity and conflict reading — reaches a trace only through
    `DecisionEngine.set_event_emitter`, which `graph/stages/run_auto.py` wires
    and a direct `prepare_auto_run` call does not. A reader looking at an
    all-empty entity column would conclude the entity guard never fires, which
    is a claim about the product this probe cannot support.

    Mirrors `graph/runner._emit_decision` rather than inventing a shape.
    """
    return Decision(
        run_id=str(run_id),
        name=name,
        value=answer.value,
        probability=answer.probability,
        probabilities=answer.probabilities,
        engine=answer.engine,
        latency_ms=answer.latency_ms,
        reasoning=answer.reasoning,
        stage=call.stage,
        call_id=call.call_id,
        batch_size=call.batch_size,
    )


def _grades(run: Any) -> list[float]:
    """The rubric's grades over the post-sanitize winners, best first.

    `kept_chunks` is what the generator would have been given, which is the
    same expanded set the gate judged — so these are the grades the gate
    actually had in front of it, not the ranks a threshold would have been
    applied to.
    """
    scores = [
        float(chunk.rerank_score)
        for chunk in run.kept_chunks
        if chunk.rerank_score is not None
    ]
    return sorted(scores, reverse=True)


def measure(
    run: Any,
    item_id: str,
    expect: str,
    intent: str,
    turns: int,
    emitted: list[Decision],
) -> dict[str, Any]:
    """The four numbers, plus what the run did, for one item's last turn.

    `emitted` is the probe's decision-emitter capture (`_entity_event`). It is
    merged with the run's own events because the two carry **different**
    questions: the evidence stage records the gate row itself, and everything
    else — every per-passage `entity_` and `conflict_` reading — arrives only
    through the emitter. Reading one without the other silently loses half the
    signal.
    """
    grades = _grades(run)
    events = [*run.decision_events, *emitted]
    entity_rows = [d for d in events if d.name.startswith("entity_")]
    entity_values = [float(d.value) for d in entity_rows if _numeric(d.value)]
    return {
        "id": item_id,
        "expect": expect,
        "intent": intent,
        "rewritten": run.rewritten,
        "turns": turns,
        "gated": expect in GATED_CLASSES,
        "top_grade": grades[0] if grades else None,
        "mean_top3": statistics.fmean(grades[:3]) if grades else None,
        "n_passages": len(grades),
        "entity_max": max(entity_values) if entity_values else None,
        "entity_measured": bool(entity_rows),
        "entity_entities": sorted({_entity_label(d.name) for d in entity_rows}),
        "abstained": run.abstain_event is not None,
        "engines": sorted({str(d.engine) for d in events}),
        "gate_engine": next(
            (str(d.engine) for d in events if d.name == "evidence"), None
        ),
        "trace_gate_rows": sorted({d.name for d in events}),
    }


def _entity_label(name: str) -> str:
    """`entity_0_1` → `1`: which named entity the reading was about.

    `checks._entity_passage_questions` names them `entity_<passage>_<entity>`,
    passage-major, so the second index is the entity — the comment at
    `_entity_passage_decision` says so and this is where it is used.
    """
    parts = name.split("_")
    return parts[-1] if len(parts) >= 3 else name


def _numeric(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


async def _run_item(
    factory: Any,
    *,
    user_id: UUID,
    question_turns: Sequence[str],
    item_id: str,
    expect: str,
    corpus_collection_ids: Sequence[UUID],
) -> dict[str, Any]:
    """One item, its turns in order on one chat, measured on the last.

    A fresh chat per item, so no item can see another's context — the same rule
    `scripts/acceptance.py` follows, for the same reason.
    """
    async with factory() as session, session.begin():
        chat = Chat(user_id=user_id, title=f"calibrate:{item_id}")
        session.add(chat)
        await session.flush()
        scope = await resolve_scope(session, chat, list(corpus_collection_ids))
        chat_id = chat.id

    run = None
    emitted: list[Decision] = []
    for turn in question_turns:
        async with factory() as session, session.begin():
            user_message = Message(
                chat_id=chat_id, role="user", content=turn, status="complete"
            )
            assistant_message = Message(chat_id=chat_id, role="assistant", content="", status=None)
            session.add_all([user_message, assistant_message])
            await session.flush()
            message_id = assistant_message.id

        engine = DecisionEngine()
        pipeline_run_id = uuid4()

        # Per turn, not accumulated: a two-turn item is measured on its LAST
        # turn, so the first turn's rows must not be in the record. And it must
        # not be cleared *after* the run and before measuring — that empties it
        # entirely, and an all-empty entity column reads as "the entity guard
        # never fires", which is a claim about the product rather than about
        # the probe.
        emitted = []

        async def emit(
            name: str,
            answer: Answer,
            call: Any,
            _rows: list[Decision] = emitted,
            _run_id: UUID = pipeline_run_id,
        ) -> None:
            _rows.append(_entity_event(name, answer, call, _run_id))

        # The one thing `run_auto.run_auto` does that a direct
        # `prepare_auto_run` call does not, and without which every
        # per-passage entity reading is invisible to this probe.
        engine.set_event_emitter(emit)

        run = await prepare_auto_run(
            factory,
            AutoRunInput(
                run_id=pipeline_run_id,
                message_id=message_id,
                chat_id=chat_id,
                user_id=user_id,
                question=turn,
                litellm_model=GENERATOR_MODEL,
                small_model=SMALL_MODEL,
                context_window=CONTEXT_WINDOW,
                source="upload",
                client_filters=ClientFilters(),
                collection_ids=scope,
            ),
            engine,
        )
    assert run is not None
    # No `stream_answer()`, no `finalize_*`: the generator and the reviewer are
    # the expensive half and the gate never sees either. `latency_ms` is
    # therefore the cost of the stages this probe is actually calibrating.
    return measure(run, item_id, expect, run.ingress.intent, len(question_turns), emitted)


async def probe(dataset: str, only: str | None) -> list[dict[str, Any]]:
    factory = get_session_factory()
    state = _load_json(STATE_FILE) if STATE_FILE.exists() else {}
    rows: list[dict[str, Any]] = []

    if dataset == "books":
        items = [
            (str(row["id"]), str(row["expect"]), [str(t) for t in row["turns"]])
            for row in _load_json(BOOKS_SET)["items"]
        ]
        # The books are `visibility='shared'`, so every user's resolved scope
        # carries them (ADR-002) and no private eval collection is in scope.
        scope_by_id: dict[str, str] = {}
    elif dataset == "entity_mismatch":
        entity_rows = _load_json(ENTITY_SET)["items"]
        items = [
            (str(row["id"]), "not_in_sources", [str(row["question"])])
            for row in entity_rows
        ]
        scope_by_id = {
            str(row["id"]): str(row.get("scope_corpus") or "") for row in entity_rows
        }
    else:
        raise ProbeError(f"unknown dataset {dataset!r}")

    if only:
        wanted = {part.strip() for part in only.split(",") if part.strip()}
        items = [row for row in items if row[0] in wanted]
        missing = wanted - {row[0] for row in items}
        if missing:
            raise ProbeError(f"no such item(s) in the {dataset} set: {sorted(missing)}")

    async with factory() as session:
        user_id = await _eval_user_id(session)

    for index, (item_id, expect, turns) in enumerate(items, start=1):
        print(f"  [{index}/{len(items)}] {item_id} ({expect})", flush=True)
        row = await _run_item(
            factory,
            user_id=user_id,
            question_turns=turns,
            item_id=item_id,
            expect=expect,
            corpus_collection_ids=(
                _corpus_ids(state, scope_by_id[item_id]) if scope_by_id else []
            ),
        )
        rows.append(row)
        print(
            f"      top={_fmt(row['top_grade'])} mean3={_fmt(row['mean_top3'])} "
            f"entity={_fmt(row['entity_max'])} abstained={row['abstained']}",
            flush=True,
        )
    return rows


def _fmt(value: float | None) -> str:
    return "  -  " if value is None else f"{value:5.3f}"


def write_report(dataset: str, rows: list[dict[str, Any]]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    sha = _head_sha()
    path = OUT_DIR / f"gate-calibration-{dataset}-{stamp}-{sha}.json"
    gated = [r for r in rows if r["gated"]]
    payload = {
        "dataset": dataset,
        "measured_at": stamp,
        "commit": sha,
        "rows": rows,
        "summary": {
            "gated": len(gated),
            "answer": sum(1 for r in gated if r["expect"] == "answer"),
            "not_in_sources": sum(1 for r in gated if r["expect"] == "not_in_sources"),
            "skipped_ungated": len(rows) - len(gated),
            "engines": sorted({e for r in rows for e in r["engines"]}),
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _head_sha() -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            cwd=ROOT,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def print_table(dataset: str, rows: list[dict[str, Any]]) -> None:
    print()
    print(f"== {dataset}: gate calibration ==")
    print(f"{'id':<32}{'expect':<16}{'top':>7}{'mean3':>8}{'ent':>7}  {'gate'}")
    for row in rows:
        print(
            f"{row['id'][:31]:<32}{row['expect'][:15]:<16}"
            f"{_fmt(row['top_grade']):>7}{_fmt(row['mean_top3']):>8}"
            f"{_fmt(row['entity_max']):>7}"
            f"  {'declined' if row['abstained'] else 'answered'}"
        )
    gated = [r for r in rows if r["gated"]]
    if gated:
        print(
            f"\n{len(gated)} gated items: "
            f"{sum(1 for r in gated if r['expect'] == 'answer')} answer, "
            f"{sum(1 for r in gated if r['expect'] == 'not_in_sources')} not_in_sources; "
            f"{len(rows) - len(gated)} never reach the gate and are excluded from every table."
        )


def propose_gate(rows: list[dict[str, Any]], allowed_misses: int = 1) -> dict[str, Any]:
    """Proposed `evidence_floor` and `stream_line` for one reranker, by the rule
    `decisions/thresholds.py` documents for Jev's values (R2c item 4).

    * **floor** sits below the lowest answerable reading, except the budgeted
      miss(es) (`allowed_misses`, the brief's one known miss), and above the
      highest should-decline reading it must block. "Must block" = every
      should-decline reading below that lowest answerable. Placed at the
      midpoint, margins reported both sides.
    * **stream line** sits above the highest should-decline reading overall, at
      the lowest tenth above it.

    If no should-decline reading falls below the lowest answerable, there is no
    separation and nothing is proposed: that is a finding about the reranker,
    not an error. Never edits `thresholds.py`; a human pastes reviewed values.
    """
    gated = [r for r in rows if r["gated"] and r["mean_top3"] is not None]
    answers = sorted(r["mean_top3"] for r in gated if r["expect"] == "answer")
    declines = sorted(r["mean_top3"] for r in gated if r["expect"] == "not_in_sources")
    if len(answers) <= allowed_misses or not declines:
        return {"separation": False, "why": "need answerable and should-decline readings"}
    lowest = answers[allowed_misses]
    blocked = [d for d in declines if d < lowest]
    if not blocked:
        return {
            "separation": False,
            "why": f"every should-decline reading is >= the lowest answerable ({lowest:.4f})",
            "lowest_answerable": lowest,
            "highest_decline": declines[-1],
        }
    highest_blocked = blocked[-1]
    floor = round((lowest + highest_blocked) / 2, 3)
    stream = round((math.floor(declines[-1] * 10) + 1) / 10, 2)
    return {
        "separation": True,
        "evidence_floor": floor,
        "floor_margin_below_answerable": round(lowest - floor, 4),
        "floor_margin_above_blocked": round(floor - highest_blocked, 4),
        "lowest_answerable": lowest,
        "budgeted_misses": answers[:allowed_misses],
        "highest_blocked_decline": highest_blocked,
        "stream_line": stream,
        "stream_margin_above_highest_decline": round(stream - declines[-1], 4),
        "highest_decline": declines[-1],
        "declines_blocked": len(blocked),
        "declines_total": len(declines),
    }


def print_proposal(reranker: str, proposal: dict[str, Any]) -> None:
    print(f"\n== proposed gate for reranker {reranker!r} (NOT written anywhere) ==")
    if not proposal["separation"]:
        print(f"no separation: {proposal['why']}. Nothing proposed.")
        return
    for key, value in proposal.items():
        if key != "separation":
            print(f"  {key:<38}{value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default=None,
        choices=["books", "entity_mismatch"],
        help="which set to calibrate on (they are calibrated separately: different corpora)",
    )
    parser.add_argument("--items", default=None, help="comma-separated item ids, to re-run some")
    parser.add_argument(
        "--reranker",
        default=None,
        help="registry id (cohere, nvidia, fused, jev): run BOTH sets through that reranker, "
        "print the separation table and a proposed floor / stream line; edits nothing",
    )
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is not set; the probe reads a real corpus")

    if args.reranker:
        return _calibrate_reranker(args.reranker, args.dataset, args.items)

    dataset = args.dataset or "books"
    print(f"==> calibrating the evidence gate on the {dataset} set")
    rows = asyncio.run(probe(dataset, args.items))
    print_table(dataset, rows)
    path = write_report(dataset, rows)
    print(f"\nwrote {path}")
    return 0


def _calibrate_reranker(reranker: str, dataset: str | None, items: str | None) -> int:
    from retrieval.rerank import RERANKERS
    from runtime import RuntimeSettings, set_runtime_settings

    if reranker not in RERANKERS:
        raise SystemExit(f"unknown reranker {reranker!r}; known: {sorted(RERANKERS)}")
    if not RERANKERS[reranker].key_present(get_settings()):
        raise SystemExit(f"reranker {reranker!r} has no API key configured; nothing to measure")
    set_runtime_settings(RuntimeSettings.from_data(0, {"retrieval": {"reranker": reranker}}))
    # Measurement mode: an uncalibrated reranker has no floor, which is exactly
    # why it is being measured. The gate lookup would refuse it, so read the
    # raw grade instead; nothing is decided from this run.
    import graph.stages.evidence_stage as evidence_stage

    evidence_stage.reranker_threshold = lambda name, rid: 0.0  # type: ignore[assignment,attr-defined]
    all_rows: list[dict[str, Any]] = []

    # One event loop for every set: the session factory is cached and bound to
    # the loop that first used it, so a second asyncio.run() would fail on it.
    async def run_sets() -> None:
        for name in [dataset] if dataset else ["books", "entity_mismatch"]:
            print(f"==> {reranker}: {name} set")
            rows = await probe(name, items)
            print_table(f"{name} / {reranker}", rows)
            all_rows.extend(rows)

    asyncio.run(run_sets())
    path = write_report(f"{reranker}-all", all_rows)
    print(f"\nwrote {path}")
    print_proposal(reranker, propose_gate(all_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
