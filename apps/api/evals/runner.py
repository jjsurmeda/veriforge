"""Eval runner (TRD §15): executes each dataset item through the real Fast
mode pipeline and records scores into eval_runs/eval_results.

Usage:
  uv run python -m evals.loader                 # once: items + corpus
  uv run python -m evals.runner                 # all 50 items
  uv run python -m evals.runner --subset fast20 # the CI gate subset
  uv run python -m evals.runner --baseline      # store baseline.json

Credits are recorded as token counts until slice 7's ledger (TRD §14).
The abstention metric is recorded but the gate treats it as pass-through
until slice 4 lands abstention as a decision (TRD §17 build order).
"""

import argparse
import asyncio
import json
import logging
import statistics
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.ids import uuid7
from db.models import Chat, EvalDataset, EvalItem, EvalResult, EvalRun, Message, User
from db.session import get_session_factory
from evals.judge import judge_answer
from evals.loader import EVAL_USER_EMAIL, STATE_FILE
from graph.fast import FastRunInput, finalize_fast_run, prepare_fast_run
from graph.generate import build_grounded_messages
from retrieval.context import count_tokens
from retrieval.filters import ClientFilters

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parents[3] / "evals" / "seed"
BASELINE_FILE = SEED_DIR / "baseline.json"
GENERATOR_MODEL = "openrouter/openai/gpt-4o-mini"
SMALL_MODEL = "openrouter/anthropic/claude-haiku-4.5"
CONTEXT_WINDOW = 128_000


async def _run_item(
    factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    collection_id: UUID,
    eval_run_id: UUID,
    item: EvalItem,
) -> EvalResult:
    async with factory() as session, session.begin():
        chat = Chat(
            user_id=user.id,
            title=f"eval:{item.question[:40]}",
            collection_ids=[str(collection_id)],
        )
        session.add(chat)
        await session.flush()
        chat_id = chat.id
        user_message = Message(
            chat_id=chat_id, role="user", content=item.question, status="complete"
        )
        assistant_message = Message(chat_id=chat_id, role="assistant", content="", status=None)
        session.add_all([user_message, assistant_message])
        await session.flush()
        message_id = assistant_message.id
    started = time.monotonic()
    run = await prepare_fast_run(
        factory,
        FastRunInput(
            run_id=uuid7(),
            message_id=message_id,
            chat_id=chat_id,
            user_id=user.id,
            question=item.question,
            litellm_model=GENERATOR_MODEL,
            small_model=SMALL_MODEL,
            context_window=CONTEXT_WINDOW,
            source="auto",
            client_filters=ClientFilters(),
            collection_ids=[collection_id],
        ),
    )
    answer = "".join([token async for token in run.stream_answer()])
    tokens_in = sum(
        count_tokens(m["content"])
        for m in build_grounded_messages(run.rewritten, run.contexts, run.history)
    )
    tokens_out = count_tokens(answer)
    latency_ms = int((time.monotonic() - started) * 1000)
    await finalize_fast_run(
        factory, run, generate_ms=0, tokens_in=tokens_in, tokens_out=tokens_out
    )

    scores = await judge_answer(
        question=item.question,
        reference_answer=item.reference_answer,
        answer=answer,
        passages=[context.context_text for context in run.contexts],
        small_model=SMALL_MODEL,
    )
    abstained = not run.contexts or "no sources" in answer.lower()
    result = EvalResult(
        eval_run_id=eval_run_id,
        item_id=item.id,
        answer=answer,
        faithfulness=scores.faithfulness if scores else None,
        citation_precision=scores.citation_precision if scores else None,
        context_precision=scores.context_precision if scores else None,
        context_recall=scores.context_recall if scores else None,
        abstained=abstained,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    async with factory() as session, session.begin():
        session.add(result)
    return result


async def run_eval(
    *, subset: str | None, baseline: bool
) -> tuple[EvalRun, list[tuple[EvalItem, EvalResult]]]:
    if not STATE_FILE.exists():
        raise SystemExit("run `uv run python -m evals.loader` first")
    collection_id = UUID(json.loads(STATE_FILE.read_text())["corpus_collection_id"])
    payload = json.loads((SEED_DIR / "items.json").read_text(encoding="utf-8"))
    fast20 = set(payload.get("fast20_ids", []))
    seed_ids = _seed_ids(payload)

    factory = get_session_factory()
    async with factory() as session, session.begin():
        user = (
            await session.execute(select(User).where(User.email == EVAL_USER_EMAIL))
        ).scalar_one()
        dataset = (
            await session.execute(select(EvalDataset).where(EvalDataset.name == "seed"))
        ).scalar_one()
        items = (
            await session.execute(
                select(EvalItem)
                .where(EvalItem.dataset_id == dataset.id)
                .order_by(EvalItem.created_at, EvalItem.id)
            )
        ).scalars().all()
        if subset == "fast20":
            items = [i for i in items if seed_ids.get(i.question) in fast20]
        eval_run = EvalRun(dataset_id=dataset.id, mode="fast", is_baseline=baseline)
        session.add(eval_run)
        await session.flush()
        eval_run_id = eval_run.id

    results: list[tuple[EvalItem, EvalResult]] = []
    for item in items:
        result = await _run_item(
            factory,
            user=user,
            collection_id=collection_id,
            eval_run_id=eval_run_id,
            item=item,
        )
        results.append((item, result))
        logger.info(
            "eval item done",
            extra={
                "item": seed_ids.get(item.question, str(item.id)),
                "faithfulness": result.faithfulness,
            },
        )
    return eval_run, results


def _seed_ids(payload: dict[str, object]) -> dict[str, str]:
    rows = payload["items"]
    assert isinstance(rows, list)
    return {str(row["question"]): str(row["id"]) for row in rows}


def aggregate(results: list[tuple[EvalItem, EvalResult]]) -> dict[str, float | None]:
    def mean(values: list[float]) -> float | None:
        return statistics.mean(values) if values else None

    faithfulness = mean([r.faithfulness for _, r in results if r.faithfulness is not None])
    abstain_items = [(i, r) for i, r in results if i.should_abstain]
    abstention_accuracy = (
        mean([1.0 if r.abstained else 0.0 for _, r in abstain_items])
        if abstain_items
        else None
    )
    latencies = sorted(r.latency_ms for _, r in results)
    p50 = float(statistics.median(latencies)) if latencies else None
    return {
        "faithfulness": faithfulness,
        "abstention_accuracy": abstention_accuracy,
        "p50_latency_ms": p50,
        "items": float(len(results)),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Veriforge eval runner")
    parser.add_argument("--subset", choices=["fast20"], default=None)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()

    eval_run, results = await run_eval(subset=args.subset, baseline=args.baseline)
    summary = aggregate(results)
    print(json.dumps({"eval_run": str(eval_run.id), **summary}, indent=2))
    if args.baseline:
        BASELINE_FILE.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"baseline written to {BASELINE_FILE}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
