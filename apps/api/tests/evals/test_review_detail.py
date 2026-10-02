"""Each eval result records its claims, their verdicts, and the contexts (item 3).

Faithfulness is a mean over the reviewer's per-claim verdicts, so a
faithfulness number that moves between two runs cannot say which claim moved.
D3 could name `multihop-05` and `lookup-01` and nothing below them, because the
per-item rows are dropped with the gate's database.

These drive the real `_run_item` with the pipeline, reviewer and judge stubbed —
so they check that the detail is persisted in the shape the export reads. No
provider call, no network, no live run.
"""

import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import EvalDataset, EvalItem, EvalResult, EvalRun, Plan, User
from db.session import get_session_factory
from evals import runner
from evals.attribution import Attribution
from evals.loader import EVAL_USER_EMAIL

pytestmark = pytest.mark.asyncio


class _FakeRun:
    """The pipeline surface `_run_item` touches."""

    def __init__(self, contexts: list[Any]) -> None:
        self.latency_ms: dict[str, int] = {"retrieve": 100}
        self.contexts = contexts
        self.abstain_event = None
        self.rewritten = "q"
        self.history: list[tuple[str, str]] = []

    async def stream_answer(self) -> AsyncIterator[str]:
        yield "answer"

    async def stream_answer_with_thinking(self) -> AsyncIterator[tuple[str, str]]:
        yield ("content", "answer")


def _context(index: int, text: str) -> Any:
    """An `ExpandedContext`-shaped stub.

    `build_grounded_messages` renders each source block from the chunk, so the
    stub carries the fields that touches rather than the whole `ScoredChunk`.
    """
    return type(
        "Ctx",
        (),
        {
            "chunk": type(
                "Chunk",
                (),
                {
                    "chunk_id": UUID(int=index),
                    "document_id": UUID(int=100 + index),
                    "document_name": f"doc-{index}.md",
                    "page": index,
                },
            )(),
            "context_text": text,
        },
    )()


async def _seed(db: AsyncSession) -> tuple[User, EvalItem]:
    plan_id = (await db.execute(select(Plan.id).where(Plan.name == "free"))).scalar_one()
    user = User(email=EVAL_USER_EMAIL, role="user", plan_id=plan_id, status="active")
    dataset = EvalDataset(name="seed")
    db.add_all([user, dataset])
    await db.flush()
    item = EvalItem(
        dataset_id=dataset.id,
        category="single_document_lookup",
        question="How long is the warranty?",
        reference_answer="12 months",
        should_abstain=False,
    )
    db.add(item)
    db.add(EvalRun(dataset_id=dataset.id, mode="auto", is_baseline=False))
    await db.commit()
    return user, item


async def _run_one(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    *,
    contexts: list[Any],
    review: Any,
    abstain: bool = False,
) -> EvalResult:
    """Drive the real `_run_item` with everything but the reviewer stubbed."""
    user, item = await _seed(db)
    state = tmp_path / "loaded.json"
    state.write_text(json.dumps({"corpus_collection_id": str(UUID(int=1))}))
    monkeypatch.setattr(runner, "STATE_FILE", state)

    run = _FakeRun(contexts)
    if abstain:
        run.abstain_event = cast(Any, object())

    async def fake_prepare(*_a: Any, **_k: Any) -> _FakeRun:
        return run

    async def fake_finalize(*_a: Any, **_k: Any) -> None:
        return None

    async def fake_resolve_scope(*_a: Any, **_k: Any) -> list[UUID]:
        return []

    async def fake_attribute(total_ms: float, ids: list[Any]) -> Attribution:
        return Attribution(total_ms=total_ms, provider_ms=0, attributed=0, unattributed=0)

    async def fake_judge(**_k: Any) -> None:
        return None

    async def fake_review(**_k: Any) -> Any:
        return review

    monkeypatch.setattr(runner, "prepare_auto_run", fake_prepare)
    monkeypatch.setattr(runner, "finalize_auto_run", fake_finalize)
    monkeypatch.setattr(runner, "resolve_scope", fake_resolve_scope)
    monkeypatch.setattr(runner, "attribute", fake_attribute)
    monkeypatch.setattr(runner, "judge_answer", fake_judge)
    monkeypatch.setattr(runner, "review_answer", fake_review)

    eval_run_id = (await db.execute(select(EvalRun.id))).scalar_one()
    result, _ = await runner._run_item(
        get_session_factory(), user=user, eval_run_id=eval_run_id, item=item
    )
    return result


def _review(claims: list[Any], scores: Any = None, revised: str | None = None) -> Any:
    from graph.review import ReviewResult

    return ReviewResult(claims=claims, scores=scores, revised_text=revised)


async def test_each_result_records_its_claims_with_verdicts(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The evidence a faithfulness swing has to be read against: the claim
    text, its citation ids, whether it is factual, the verdict, the
    probability, and which engine judged it."""
    from graph.review import ExtractedClaim, ReviewScores, VerifiedClaim

    result = await _run_one(
        db,
        monkeypatch,
        tmp_path,
        contexts=[_context(1, "The AW-2000 carries a 12 month warranty.")],
        review=_review(
            [
                VerifiedClaim(
                    ExtractedClaim("c1", "The warranty is 12 months.", [1], True),
                    "supported",
                    0.9,
                    "jev",
                ),
                VerifiedClaim(
                    ExtractedClaim("c2", "The blade is titanium.", [1], True),
                    "unsupported",
                    0.0,
                    "jev",
                ),
            ],
            ReviewScores(faithfulness=0.5, min_support=0.0, citation_precision=0.5),
        ),
    )

    detail = result.review_detail
    assert detail is not None
    assert detail["claims"] == [
        {
            "id": "c1",
            "text": "The warranty is 12 months.",
            "citation_ids": [1],
            "is_factual": True,
            "verdict": "supported",
            "p_supported": 0.9,
            "engine": "jev",
        },
        {
            "id": "c2",
            "text": "The blade is titanium.",
            "citation_ids": [1],
            "is_factual": True,
            "verdict": "unsupported",
            "p_supported": 0.0,
            "engine": "jev",
        },
    ]
    # The mean the gate gates on, over exactly the claims above.
    assert result.faithfulness == 0.5


async def test_the_contexts_are_recorded_as_digests_of_the_passages(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A citation or context difference is one of the four candidate sources of
    a faithfulness swing, so retrieval has to be recorded too — as a digest,
    because two runs only need to be comparable, not the text re-read."""
    passages = ["first passage", "second passage, longer than the first"]
    contexts = [_context(index, text) for index, text in enumerate(passages, start=1)]

    result = await _run_one(db, monkeypatch, tmp_path, contexts=contexts, review=_review([]))

    detail = result.review_detail
    assert detail is not None
    recorded = detail["contexts"]
    assert [row["n"] for row in recorded] == [1, 2]
    for index, row in enumerate(recorded):
        assert row["digest"] == hashlib.sha256(passages[index].encode()).hexdigest()[:16]
        assert row["chars"] == len(passages[index])
        assert row["chunk_id"]


async def test_a_revision_is_recorded_because_it_changes_the_answer(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """`review_revised` in stage_ms: the reviewer's revision pass replaced the
    answer the user saw, so a run where it fired is not comparable to one where
    it did not."""
    result = await _run_one(
        db,
        monkeypatch,
        tmp_path,
        contexts=[_context(1, "passage")],
        review=_review([], None, revised="A corrected answer."),
    )
    assert (result.stage_ms or {})["review_revised"] == 1


async def test_an_unrevised_answer_records_zero(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The other half of the flag: 0 is recorded, not the key's absence, so a
    comparison between two runs does not have to distinguish "did not revise"
    from "was not measured"."""
    result = await _run_one(
        db, monkeypatch, tmp_path, contexts=[_context(1, "passage")], review=_review([])
    )
    assert (result.stage_ms or {})["review_revised"] == 0


async def test_the_detail_survives_the_round_trip_to_the_database(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The gate's database is dropped on exit, so what has to be readable later
    has to be committed, not just held in memory."""
    from graph.review import ExtractedClaim, ReviewScores, VerifiedClaim

    result = await _run_one(
        db,
        monkeypatch,
        tmp_path,
        contexts=[_context(1, "passage")],
        review=_review(
            [VerifiedClaim(ExtractedClaim("c1", "A claim.", [1], True), "partial", 0.5, "jev")],
            ReviewScores(0.5, 0.5, 1.0),
        ),
    )

    persisted = (
        await db.execute(select(EvalResult).where(EvalResult.id == result.id))
    ).scalar_one()
    assert persisted.review_detail == result.review_detail
    assert persisted.review_detail is not None
    assert persisted.review_detail["claims"][0]["verdict"] == "partial"


async def test_an_abstention_records_contexts_and_no_claims(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """An abstention asserts nothing, so it has no claims — but it did retrieve,
    and the contexts are what prove it declined against the right material."""

    async def must_not_review(**_k: Any) -> Any:
        raise AssertionError("an abstention must not be reviewed")

    result = await _run_one(
        db,
        monkeypatch,
        tmp_path,
        contexts=[_context(1, "passage"), _context(2, "another")],
        review=_review([]),
        abstain=True,
    )

    assert result.abstained is True
    assert result.faithfulness == 1.0
    detail = result.review_detail
    assert detail is not None
    assert detail["claims"] == []
    assert len(detail["contexts"]) == 2


async def test_the_export_column_is_jsonb_on_the_model() -> None:
    """A cheap guard that the model and migration 0015 agree: the export reads
    this column, so a missing one fails the run rather than the export."""
    assert EvalResult.__table__.c.review_detail.type.__class__.__name__ == "JSONB"
