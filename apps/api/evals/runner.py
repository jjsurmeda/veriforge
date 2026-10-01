"""Eval runner (TRD §15): executes each dataset item through the real Auto
pipeline and records scores into eval_runs/eval_results.

Usage:
  uv run python -m evals.loader                 # once: items + corpus
  uv run python -m evals.runner                 # all 50 items
  uv run python -m evals.runner --subset fast20 # the CI gate subset
  uv run python -m evals.runner --baseline      # store baseline.json

Interactive run credits are metered by the shared quota UsageContext; this
harness keeps its own token counters for eval-result reporting.
Slice 4 routes items through graph/auto.py — abstention accuracy is a real
check now (the slice-3 pass-through is removed in evals/gate.py).
Slice 6: faithfulness and citation precision are Reviewer-computed
(graph/review.py, TR-2/TR-3) — the interim judge is retired from the gate;
numbers are rebaselined against slice 5's stored baseline.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import statistics
import time
from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
from sqlalchemy import select
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from chats.scope import resolve_scope
from config import get_settings
from db.ids import uuid7
from db.models import Chat, EvalDataset, EvalItem, EvalResult, EvalRun, Message, User
from decisions import DecisionEngine
from evals.attribution import GenerationRef, attribute, record_generation_ids
from evals.judge import judge_answer
from evals.loader import EVAL_USER_EMAIL, STATE_FILE
from graph.auto import AutoRunInput, finalize_auto_run, prepare_auto_run
from graph.deep import DeepRunInput, finalize_deep_run, prepare_deep_run
from graph.generate import build_grounded_messages
from graph.review import review_answer
from retrieval.context import count_tokens
from retrieval.filters import ClientFilters

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parents[3] / "evals" / "seed"
BASELINE_FILE = SEED_DIR / "baseline.json"
BASELINE_FAST20_FILE = SEED_DIR / "baseline_fast20.json"
# Both roles are gpt-4o-mini because that is what the product runs today, not
# because it is the better model: `model_roles` has gpt-4o-mini in every LLM
# role with claude-haiku-4.5 only as the generator's and planner's *fallback*.
# The harness used to pin haiku for the small role, so the gate measured
# rewrite, query variants and claim extraction on a model the product does not
# use there — a comparison between the harness and the product rather than a
# regression check on it. P7 chooses the production models per role and
# rebaselines; until then the gate measures what ships. (O2)
GENERATOR_MODEL = "openrouter/openai/gpt-4o-mini"
SMALL_MODEL = "openrouter/openai/gpt-4o-mini"
CONTEXT_WINDOW = 128_000

# The harness drives one item at a time, so its own small pool is the whole
# connection budget; db/session.py's server defaults (5+10) are sized for a
# web process, not a batch job. ponytail: one item at a time — raise this and
# give the pool matching headroom if a run ever needs to overlap items.
EVAL_POOL_SIZE = 2
EVAL_MAX_OVERFLOW = 2
# A ParadeDB backend crash takes every client connection with it and refuses
# new ones for ~30s (verified: 2026-09-27 07:24:47 "server process exited with
# exit code 2" → "the database system is not yet accepting connections").
# Without a retry that window silently kills every item it touches; with one
# the item is re-measured instead. The retry cannot hide a product defect: a
# still-failing item is persisted with `error` and fails the gate.
DB_RETRY_DELAYS_S = (1.0, 3.0, 6.0)


def _eval_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        get_settings().database_url,
        pool_size=EVAL_POOL_SIZE,
        max_overflow=EVAL_MAX_OVERFLOW,
        pool_pre_ping=True,
        connect_args={"timeout": 10},
    )
    return async_sessionmaker(engine, expire_on_commit=False)


def _is_transient_db_error(exc: BaseException) -> bool:
    # asyncpg.PostgresError covers CannotConnectNowError (the database is in
    # recovery) and ConnectionDoesNotExistError (a killed backend's prepared
    # statement). InterfaceError is a dead pooled connection and
    # PoolTimeoutError is a checkout that waited out pool_timeout.
    return isinstance(
        exc, asyncpg.PostgresError | asyncpg.InterfaceError | OSError | PoolTimeoutError
    )


async def _retry_transient[T](work: Callable[[], Awaitable[T]], *, what: str) -> T:
    for attempt, delay in enumerate((*DB_RETRY_DELAYS_S, 0.0)):
        try:
            return await work()
        except Exception as exc:
            if attempt == len(DB_RETRY_DELAYS_S) or not _is_transient_db_error(exc):
                raise
            logger.warning(
                "eval item retrying after db error",
                extra={"what": what, "attempt": attempt + 1, "error": repr(exc)[:200]},
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


async def _run_item(
    factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    eval_run_id: UUID,
    item: EvalItem,
    mode: str = "auto",
) -> tuple[EvalResult, list[GenerationRef]]:
    async with factory() as session, session.begin():
        chat = Chat(
            user_id=user.id,
            title=f"eval:{item.question[:40]}",
        )
        session.add(chat)
        await session.flush()
        chat_id = chat.id
        scope = await resolve_scope(session, chat)
        user_message = Message(
            chat_id=chat_id, role="user", content=item.question, status="complete"
        )
        assistant_message = Message(chat_id=chat_id, role="assistant", content="", status=None)
        session.add_all([user_message, assistant_message])
        await session.flush()
        message_id = assistant_message.id
    started = time.monotonic()
    async with record_generation_ids() as generation_ids:
        engine = DecisionEngine()
        pipeline_run_id = uuid7()
        # source="upload": eval runs are documents-only, the same as the UI
        # default (ChatComposer sends "upload"/"both", never "auto"), because
        # the seed set is "over the demo corpus" (TRD §15). "auto" routed to
        # Tavily and had should-abstain items answered from the web.
        if mode == "deep":
            deep_run = await prepare_deep_run(
                factory,
                DeepRunInput(
                    run_id=pipeline_run_id,
                    message_id=message_id,
                    chat_id=chat_id,
                    user_id=user.id,
                    question=item.question,
                    litellm_model=GENERATOR_MODEL,
                    small_model=SMALL_MODEL,
                    context_window=CONTEXT_WINDOW,
                    source="upload",
                    client_filters=ClientFilters(),
                    collection_ids=scope,
                ),
                engine,
            )
            generate_started = time.monotonic()
            answer = "".join(
                [
                    token
                    async for kind, token in deep_run.stream_answer_with_thinking()
                    if kind == "content"
                ]
            )
            generate_ms = int((time.monotonic() - generate_started) * 1000)
            tokens_in = sum(
                count_tokens(m["content"])
                for m in build_grounded_messages(
                    deep_run.rewritten, deep_run.contexts, deep_run.history
                )
            )
            tokens_out = count_tokens(answer)
            latency_ms = int((time.monotonic() - started) * 1000)
            stage_ms = {**deep_run.latency_ms, "generate": generate_ms}
            await finalize_deep_run(
                factory,
                deep_run,
                generate_ms=generate_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            abstained = deep_run.abstain_event is not None
            contexts = deep_run.contexts
        else:
            run = await prepare_auto_run(
                factory,
                AutoRunInput(
                    run_id=pipeline_run_id,
                    message_id=message_id,
                    chat_id=chat_id,
                    user_id=user.id,
                    question=item.question,
                    litellm_model=GENERATOR_MODEL,
                    small_model=SMALL_MODEL,
                    context_window=CONTEXT_WINDOW,
                    source="upload",
                    client_filters=ClientFilters(),
                    collection_ids=scope,
                ),
                engine,
            )
            generate_started = time.monotonic()
            answer = "".join([token async for token in run.stream_answer()])
            generate_ms = int((time.monotonic() - generate_started) * 1000)
            tokens_in = sum(
                count_tokens(m["content"])
                for m in build_grounded_messages(run.rewritten, run.contexts, run.history)
            )
            tokens_out = count_tokens(answer)
            latency_ms = int((time.monotonic() - started) * 1000)
            stage_ms = {**run.latency_ms, "generate": generate_ms}
            await finalize_auto_run(
                factory, run, generate_ms=generate_ms, tokens_in=tokens_in, tokens_out=tokens_out
            )
            abstained = run.abstain_event is not None
            contexts = run.contexts

    # KI-18 (D2 2c): the generation ids are collected here but the stats
    # lookups are deferred to run_eval — a generation's record lands ~20 s
    # after the call, so a per-item wait cost ~20 s per item; one wait at
    # the end covers the whole run. stage_ms gets provider_ms /
    # our_overhead_ms filled in there.
    # Slice 6: faithfulness and citation precision come from the real
    # Reviewer (TR-2/TR-3) — this is the rebaseline that matters. The
    # post-hoc judge only scores context precision/recall (TRD §10 keeps
    # the two mechanisms separate). Abstentions assert nothing: 1.0.
    faithfulness: float | None = None
    citation_precision: float | None = None
    # The claims and their verdicts, kept per item. Faithfulness is a mean over
    # them, so when it moves between two runs the mean alone cannot say which
    # claim moved or why — a different answer, a different extraction, the same
    # claim judged differently, or a different context. `eval-gate-local` drops
    # the database on exit, so this has to be persisted to be read at all.
    claim_detail: list[dict[str, Any]] = []
    # The retrieved contexts, whether or not the item abstained: a citation or
    # context difference between two runs is one of the four candidate sources
    # for a faithfulness swing, so it has to be recorded to be ruled out. A
    # digest, not the text — the passages are long and the comparison only
    # needs to know whether they were the same ones.
    context_detail = [
        {
            "n": index,
            "chunk_id": str(context.chunk.chunk_id),
            "document_id": str(context.chunk.document_id or ""),
            "chars": len(context.context_text),
            "digest": hashlib.sha256(context.context_text.encode()).hexdigest()[:16],
        }
        for index, context in enumerate(contexts, start=1)
    ]
    if not abstained:
        review_started = time.monotonic()
        review = await review_answer(
            engine=engine,
            run_id=str(pipeline_run_id),
            answer=answer,
            contexts=contexts,
            citation_count=len(contexts),
            small_model=SMALL_MODEL,
            litellm_model=GENERATOR_MODEL,
        )
        stage_ms["review"] = int((time.monotonic() - review_started) * 1000)
        if review.scores is not None:
            faithfulness = review.scores.faithfulness
            citation_precision = review.scores.citation_precision
        claim_detail = [
            {
                "id": verified.claim.claim_id,
                "text": verified.claim.text,
                "citation_ids": verified.claim.citation_ids,
                "is_factual": verified.claim.is_factual,
                "verdict": verified.verdict,
                "p_supported": verified.p_supported,
                "engine": verified.engine,
            }
            for verified in review.claims
        ]
        stage_ms["review_revised"] = int(review.revised_text is not None)
    else:
        faithfulness = 1.0
        citation_precision = 1.0
    scores = await judge_answer(
        question=item.question,
        reference_answer=item.reference_answer,
        answer=answer,
        passages=[context.context_text for context in contexts],
        small_model=SMALL_MODEL,
    )
    result = EvalResult(
        eval_run_id=eval_run_id,
        item_id=item.id,
        answer=answer,
        faithfulness=faithfulness,
        citation_precision=citation_precision,
        context_precision=scores.context_precision if scores else None,
        context_recall=scores.context_recall if scores else None,
        abstained=abstained,
        latency_ms=latency_ms,
        stage_ms=stage_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        review_detail={"claims": claim_detail, "contexts": context_detail},
    )
    async with factory() as session, session.begin():
        session.add(result)
    return result, list(generation_ids)


async def run_eval(
    *, subset: str | None, baseline: bool, mode: str = "auto", category: str | None = None
) -> tuple[EvalRun, list[tuple[EvalItem, EvalResult]]]:
    if not STATE_FILE.exists():
        raise SystemExit("run `uv run python -m evals.loader` first")
    if not json.loads(STATE_FILE.read_text()).get("corpus_collection_id"):
        raise SystemExit("seed corpus missing: run `uv run python -m evals.loader` first")
    payload = json.loads((SEED_DIR / "items.json").read_text(encoding="utf-8"))
    fast20 = set(payload.get("fast20_ids", []))
    seed_ids = _seed_ids(payload)

    factory = _eval_factory()
    async with factory() as session, session.begin():
        user = (
            await session.execute(select(User).where(User.email == EVAL_USER_EMAIL))
        ).scalar_one()
        dataset = (
            await session.execute(select(EvalDataset).where(EvalDataset.name == "seed"))
        ).scalar_one()
        items = (
            (
                await session.execute(
                    select(EvalItem)
                    .where(EvalItem.dataset_id == dataset.id)
                    .order_by(EvalItem.created_at, EvalItem.id)
                )
            )
            .scalars()
            .all()
        )
        if subset == "fast20":
            items = [i for i in items if seed_ids.get(i.question) in fast20]
        if category is not None:
            items = [i for i in items if i.category == category]
        eval_run = EvalRun(dataset_id=dataset.id, mode=mode, is_baseline=baseline)
        session.add(eval_run)
        await session.flush()
        eval_run_id = eval_run.id

    results: list[tuple[EvalItem, EvalResult]] = []
    pending_ids: dict[int, list[GenerationRef]] = {}  # id(result) -> its LLM calls
    # One item at a time. A concurrent `gather` here would multiply the DB
    # footprint by the item count; if that ever becomes worth it, raise
    # EVAL_POOL_SIZE/EVAL_MAX_OVERFLOW with it.
    for item in items:
        try:
            result, generation_ids = await _retry_transient(
                partial(
                    _run_item,
                    factory,
                    user=user,
                    eval_run_id=eval_run_id,
                    item=item,
                    mode=mode,
                ),
                what=seed_ids.get(item.question, str(item.id)),
            )
            if generation_ids:
                pending_ids[id(result)] = generation_ids
        except Exception as exc:
            # An item that raised was not measured. Persist the failure so the
            # report can count it and the gate can refuse it, instead of
            # letting a latency_ms=0 row drag the median down.
            logger.exception(
                "eval item failed",
                extra={"item": seed_ids.get(item.question, str(item.id))},
            )
            result = EvalResult(
                eval_run_id=eval_run_id,
                item_id=item.id,
                answer="",
                latency_ms=0,
                error=f"{type(exc).__name__}: {exc}"[:2000],
            )
            async with factory() as session, session.begin():
                session.add(result)
        results.append((item, result))
        logger.info(
            "eval item done",
            extra={
                "item": seed_ids.get(item.question, str(item.id)),
                "faithfulness": result.faithfulness,
            },
        )

    # KI-18 (D2 2c): split each item's measured wall clock into the part
    # OpenRouter spent generating and the part that is ours, now that the
    # whole run has finished — the stats record lands ~20 s after each
    # call, so one wait here covers every item instead of ~20 s per item.
    # Only the LLM calls made inside the timed window count, so the
    # reviewer and judge are left out. An item with nothing attributed
    # records no overhead at all rather than claiming the whole wall clock
    # as ours.
    attributions = await asyncio.gather(
        *(
            attribute(result.latency_ms, pending_ids[id(result)])
            for _, result in results
            if id(result) in pending_ids
        )
    )
    attributed_results = [result for _, result in results if id(result) in pending_ids]
    for result, attribution in zip(attributed_results, attributions, strict=True):
        stage_ms = {
            **(result.stage_ms or {}),
            "provider_ms": attribution.provider_ms,
            "generations_attributed": attribution.attributed,
        }
        # KI-31: a partial attribution is reported, not discarded. The
        # provider time that did resolve stays on the item, the count of ids
        # that did not is recorded next to it, and `our_overhead_ms` is still
        # withheld because a partial sum understates provider time and would
        # overstate ours. `p50_total_ms_unattributed_items` puts the withheld
        # wall clock in the summary so the gap is visible.
        if attribution.unattributed:
            stage_ms["generations_unattributed"] = attribution.unattributed
            stage_ms["unresolved_generation_ids"] = [
                entry.describe() for entry in attribution.unresolved
            ]
        if attribution.complete:
            stage_ms["our_overhead_ms"] = attribution.overhead_ms
        result.stage_ms = stage_ms
    if attributed_results:
        async with factory() as session, session.begin():
            for result in attributed_results:
                await session.merge(result)
    return eval_run, results


def models_on_record() -> dict[str, str]:
    """The models this harness ran with, per role.

    Recorded in every run summary and in the baseline, and compared by
    `evals.gate`. A faithfulness or latency number measured on one model says
    nothing about another, so comparing a run against a baseline written with
    different models would report a regression that is really a config change
    — or hide one that is real. The gate refuses that case instead.
    """
    return {"generator": GENERATOR_MODEL, "small": SMALL_MODEL}


def _seed_ids(payload: dict[str, object]) -> dict[str, str]:
    rows = payload["items"]
    assert isinstance(rows, list)
    return {str(row["question"]): str(row["id"]) for row in rows}


def aggregate(results: list[tuple[EvalItem, EvalResult]]) -> dict[str, float | None]:
    """Roll up a run. An item whose `error` is set was never measured, so it
    is left out of every mean and every latency percentile — a zero there would
    pull the median down and hide the failure from the gate.

    `answer_rate` is the share of answerable items that produced an answer.
    It is not defined in terms of the outcome it measures, which is what
    makes it a counterweight: `faithfulness` scores an abstention 1.0, so a
    run that abstained on everything reports perfect faithfulness *and*
    perfect abstention accuracy (TRD §15)."""

    def mean(values: list[float]) -> float | None:
        return statistics.mean(values) if values else None

    scored = [(i, r) for i, r in results if not r.error]
    faithfulness = mean([r.faithfulness for _, r in scored if r.faithfulness is not None])
    context_recall = mean([r.context_recall for _, r in scored if r.context_recall is not None])
    abstain_items = [(i, r) for i, r in scored if i.should_abstain]
    abstention_accuracy = (
        mean([1.0 if r.abstained else 0.0 for _, r in abstain_items]) if abstain_items else None
    )
    answerable = [(i, r) for i, r in scored if not i.should_abstain]
    answer_rate = mean([0.0 if r.abstained else 1.0 for _, r in answerable]) if answerable else None
    latencies = sorted(r.latency_ms for _, r in scored)
    p50 = float(statistics.median(latencies)) if latencies else None
    # p50_our_overhead_ms is the strictly gated number (KI-18): wall clock
    # minus the provider time we could attribute. TRD §15: an unattributable
    # *item* records no figure, and the summary is null only when *no* call
    # was attributed — so the median runs over the attributed items, and
    # `overhead_items_attributed` says how much of the run that covers.
    overheads = [
        float(r.stage_ms["our_overhead_ms"])
        for _, r in scored
        if r.stage_ms and r.stage_ms.get("our_overhead_ms") is not None
    ]
    # KI-31: `p50_our_overhead_ms` is a median over the attributed items only,
    # and the slow items are the ones that fail to attribute, so that median
    # is biased *downward* — the gate compares a flattering subset. This is
    # the median wall clock of exactly those excluded items, so the size of
    # the flattering subset is visible in the same summary. It is reported,
    # never gated.
    unattributed_latencies = [
        float(r.latency_ms)
        for _, r in scored
        if r.stage_ms and r.stage_ms.get("generations_unattributed")
    ]
    return {
        "faithfulness": faithfulness,
        "context_recall": context_recall,
        "abstention_accuracy": abstention_accuracy,
        "answer_rate": answer_rate,
        "p50_latency_ms": p50,
        "p50_our_overhead_ms": (float(statistics.median(overheads)) if overheads else None),
        "overhead_items_attributed": float(len(overheads)),
        "p50_total_ms_unattributed_items": (
            float(statistics.median(unattributed_latencies)) if unattributed_latencies else None
        ),
        "items": float(len(results)),
        "scored": float(len(scored)),
        "failed": float(len(results) - len(scored)),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Veriforge eval runner")
    parser.add_argument("--subset", choices=["fast20"], default=None)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--mode", choices=["auto", "deep"], default="auto")
    parser.add_argument("--category", default=None)
    args = parser.parse_args()

    eval_run, results = await run_eval(
        subset=args.subset, baseline=args.baseline, mode=args.mode, category=args.category
    )
    summary = aggregate(results)
    models = models_on_record()
    print(json.dumps({"eval_run": str(eval_run.id), "models": models, **summary}, indent=2))
    if args.baseline:
        # `models` rides along in the baseline so evals.gate can refuse a
        # comparison against a run that used different models.
        BASELINE_FILE.write_text(json.dumps({"models": models, **summary}, indent=2) + "\n")
        print(f"baseline written to {BASELINE_FILE}")
        # The gate runs the fast20 subset; comparing it against a full-50
        # baseline fails on sampling noise (abstention is ~6 Bernoulli
        # trials in the subset). Store a like-for-like subset baseline too.
        fast20 = set(json.loads((SEED_DIR / "items.json").read_text()).get("fast20_ids", []))
        seed_ids = _seed_ids(json.loads((SEED_DIR / "items.json").read_text()))
        subset = [(i, r) for i, r in results if seed_ids.get(i.question) in fast20]
        subset_summary = aggregate(subset)
        BASELINE_FAST20_FILE.write_text(
            json.dumps({"models": models, **subset_summary}, indent=2) + "\n"
        )
        print(f"fast20 baseline written to {BASELINE_FAST20_FILE}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
